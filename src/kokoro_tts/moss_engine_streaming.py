"""MOSS-TTS-Nano AngeVoice 适配器的流式方法。

作为 mixin 保留，使 ``moss_engine.py`` 专注于生命周期和非流式合成，
而本模块负责 WebSocket/流式行为。
"""

from __future__ import annotations

import base64
import logging
import queue
import time
import threading
from typing import Callable

from .audio import encode_audio_segment
from .moss_runtime.streaming import (
    StreamBudgetThresholds,
    merge_codec_audio,
    resolve_stream_decode_frame_budget,
    runtime_supports_frame_streaming,
)
from .moss_runtime.audio import split_waveform_for_stream
from .workers.process_worker import EngineProcessTimeoutError

logger = logging.getLogger(__name__)


def _cancel_requested(cancel_check: Callable[[], bool] | None) -> bool:
    if cancel_check is None:
        return False
    try:
        return bool(cancel_check())
    except Exception:
        logger.debug("MOSS 取消状态检查失败", exc_info=True)
        return False


class _MossStreamCancelled(Exception):
    """客户端取消 MOSS 流式请求时使用的内部异常。"""


class MossStreamingMixin:
    def synthesize_stream(
        self,
        text,
        voice="",
        speed=1.0,
        fmt="pcm_s16le",
        prompt_audio_path: str | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ):
        """流式合成。

        进程隔离模式下，cancel_check 通过共享内存标志通知子进程在帧间隙停止，
        不杀进程，模型保持加载。非隔离模式下，cancel_check 在帧间隙检查，
        无法中断正在进行的 ONNX/CUDA 单帧推理。
        """
        if fmt not in self.SUPPORTED_STREAM_FORMATS:
            yield {"type": "error", "message": f"不支持的流式格式：{fmt}"}
            return
        try:
            self._validate_request(text=text, voice=voice, speed=speed)
        except Exception as exc:
            yield {"type": "error", "message": str(exc)}
            return

        prepared_text = self._clean_text(text)
        segments = self._segment_text(prepared_text)
        prompt_audio = prompt_audio_path or (
            str(self.config.moss_prompt_audio_path) if self.config.moss_prompt_audio_path else None
        )

        if self._process_isolated:
            yield from self._synthesize_stream_process_isolated(
                text=text,
                voice=voice,
                speed=speed,
                fmt=fmt,
                prompt_audio_path=prompt_audio,
                cancel_check=cancel_check,
            )
            return

        yield {
            "type": "started",
            "segments": len(segments),
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "format": fmt,
            "dtype": "s16le" if fmt == "pcm_s16le" else "wav",
            "model": self.engine_id,
            "voice_clone": bool(prompt_audio),
            "recommended_prebuffer_seconds": float(getattr(self.config, "moss_stream_prebuffer_seconds", 0.75)),
        }

        item_queue: queue.Queue = queue.Queue(maxsize=max(1, int(self.config.moss_stream_queue_max_items)))
        stop_event = threading.Event()
        total_done = 0

        def is_cancelled() -> bool:
            if stop_event.is_set():
                return True
            if cancel_check is None:
                return False
            try:
                return bool(cancel_check())
            except Exception:
                logger.debug("MOSS 取消状态检查失败", exc_info=True)
                return False

        def put_item(item) -> bool:
            while not is_cancelled():
                try:
                    item_queue.put(item, timeout=0.1)
                    return True
                except queue.Full:
                    continue
            return False

        def run_stream_worker() -> None:
            try:
                with self._runtime_lock:
                    self._push_stream_waveforms(
                        segments=segments,
                        voice=voice,
                        prompt_audio_path=prompt_audio,
                        put_item=put_item,
                        is_cancelled=is_cancelled,
                    )
            except _MossStreamCancelled:
                logger.info("MOSS 流式请求已取消")
            except Exception as exc:
                logger.warning("MOSS 流式请求失败：%s", exc)
                put_item(("error", exc))
            finally:
                put_item(("done", None))

        future = self._executor.submit(run_stream_worker)

        try:
            while True:
                if is_cancelled():
                    break
                try:
                    kind, payload = item_queue.get(timeout=0.2)
                except queue.Empty:
                    if future.done():
                        exc = future.exception()
                        if exc is not None:
                            logger.warning("MOSS 流式 worker 失败：%s", exc)
                            yield {"type": "segment_error", "index": total_done, "message": str(exc), "model": self.engine_id}
                        break
                    continue
                if kind == "done":
                    break
                if kind == "error":
                    yield {"type": "segment_error", "index": total_done, "message": str(payload), "model": self.engine_id}
                    break
                if kind != "audio":
                    continue
                waveform = payload
                audio_bytes = encode_audio_segment(waveform, fmt, self.sample_rate)
                yield {
                    "type": "audio",
                    "index": total_done,
                    "data": base64.b64encode(audio_bytes).decode("ascii"),
                    "format": fmt,
                    "sample_rate": self.sample_rate,
                    "channels": self.channels,
                }
                total_done += 1
        finally:
            stop_event.set()
            future.cancel()

        yield {"type": "done", "total_segments": len(segments), "total_audio_chunks": total_done}


    def _synthesize_stream_process_isolated(
        self,
        *,
        text: str,
        voice: str,
        speed: float,
        fmt: str,
        prompt_audio_path: str | None,
        cancel_check: Callable[[], bool] | None,
    ):
        """通过隔离子进程执行 MOSS 流式推理。

        取消策略在 EngineProcessClient 中统一处理：调用方提前关闭生成器时，
        父进程立即设置共享取消标志并释放请求锁；子进程在 MOSS 运行时的
        帧级检查点停止旧请求，后续请求会丢弃旧 request_id 的残留结束帧。
        这样既不会长时间卡住 WebSocket，也不会为了停止而杀掉已加载模型。
        """

        # 修复说明：同时检查 is_loaded，处理进程崩溃后 client 存在但未加载的场景。
        # 兼容旧测试/旧插件中可能传入的轻量 client stub：没有 is_loaded 时退回
        # 检查 alive，避免 AttributeError 掩盖真正的重载路径。
        client_loaded = bool(
            self._process_client is not None
            and getattr(self._process_client, "is_loaded", bool(getattr(self._process_client, "alive", False)))
        )
        if not client_loaded:
            self.load()
        if self._process_client is None:
            # 加载可能已被测试或外层取消路径取消/替换。
            yield {"type": "done", "total_segments": 0, "total_audio_chunks": 0}
            return

        # 把外部取消检查交给 EngineProcessClient.stream()。它会在生成器关闭
        # 或取消检查命中时设置共享取消标志；实际停止由子进程内的帧级检查完成。
        stream_timeout = max(
            float(getattr(self.config, "request_timeout_seconds", 300.0) or 300.0),
            float(getattr(self.config, "engine_process_stream_idle_timeout_seconds", 120.0) or 120.0),
            5.0,
        )
        saw_protocol_done = False
        saw_terminal_error = False
        next_error_index = 0
        try:
            for event in self._process_client.stream(
                {
                    "text": text,
                    "voice": voice,
                    "speed": speed,
                    "fmt": fmt,
                    "prompt_audio_path": prompt_audio_path,
                    # 跨进程不能传递 cancel_check callable，
                    # 父进程通过 EngineProcessClient.stream(cancel_check=...) 在帧间隙控制取消。
                    "cancel_check": None,
                },
                timeout=stream_timeout,
                cancel_check=cancel_check,
            ):
                if isinstance(event, dict):
                    event_type = str(event.get("type") or "")
                    if event_type == "done":
                        saw_protocol_done = True
                    elif event_type in {"error", "segment_error", "cancelled"}:
                        saw_terminal_error = True
                    if event_type == "audio":
                        try:
                            next_error_index = max(next_error_index, int(event.get("index", -1)) + 1)
                        except (TypeError, ValueError):
                            next_error_index += 1
                yield event
            if not saw_protocol_done and not saw_terminal_error and not _cancel_requested(cancel_check):
                logger.warning("MOSS 隔离流式合成提前结束，未收到协议完成帧")
                yield {
                    "type": "segment_error",
                    "index": next_error_index,
                    "message": "MOSS 流式合成提前结束，未收到完成帧；本次部分音频已丢弃",
                    "model": self.engine_id,
                }
        except EngineProcessTimeoutError as exc:
            self._mark_process_failure(timeout=stream_timeout, reason="stream_timeout")
            yield {"type": "segment_error", "index": 0, "message": str(exc), "model": self.engine_id}
            yield {"type": "done", "total_segments": 0, "total_audio_chunks": 0}
        except Exception as exc:
            self._mark_process_failure(timeout=stream_timeout, reason="stream_error")
            yield {"type": "segment_error", "index": 0, "message": str(exc), "model": self.engine_id}
            yield {"type": "done", "total_segments": 0, "total_audio_chunks": 0}

    def _push_stream_waveforms(
        self,
        *,
        segments: list[str],
        voice: str = "",
        prompt_audio_path: str | None = None,
        put_item: Callable[[tuple[str, object]], bool],
        is_cancelled: Callable[[], bool],
    ) -> None:
        prompt_audio_codes = self._resolve_prompt_audio_codes_cached(voice=voice, prompt_audio_path=prompt_audio_path)
        self._configure_runtime_generation()
        total_segments = len([item for item in segments if item.strip()])
        emitted = 0
        stream_state = {
            "emitted_samples_total": 0,
            "first_audio_emitted_at_perf": None,
            "chunk_seconds": self._stream_chunk_seconds_for_text(),
        }
        for seg in segments:
            if is_cancelled():
                raise _MossStreamCancelled()
            if not seg.strip():
                continue
            emitted += 1
            t0 = time.monotonic()
            chunks = self._stream_runtime_chunks(
                seg,
                voice=voice,
                prompt_audio_codes=prompt_audio_codes,
                put_item=put_item,
                is_cancelled=is_cancelled,
                stream_state=stream_state,
            )
            logger.info(
                "MOSS 分段 %d/%d 已流式输出（%.1fs，音频块=%d）",
                emitted,
                total_segments,
                time.monotonic() - t0,
                chunks,
            )
            if emitted < total_segments:
                silence = self._silence_array(self._segment_pause_seconds())
                if silence.size:
                    self._emit_stream_waveform(
                        silence,
                        put_item=put_item,
                        is_cancelled=is_cancelled,
                        stream_state=stream_state,
                        is_pause=True,
                    )

    def _stream_runtime_chunks(
        self,
        text: str,
        *,
        voice: str = "",
        prompt_audio_codes: list[list[int]],
        put_item: Callable[[tuple[str, object]], bool],
        is_cancelled: Callable[[], bool],
        stream_state: dict,
    ) -> int:
        if not bool(self.config.moss_realtime_streaming_decode) or not self._runtime_supports_frame_streaming():
            emitted = 0
            for waveform in self._iter_runtime_chunks(text, voice=voice, prompt_audio_codes=prompt_audio_codes):
                emitted += self._emit_stream_waveform(
                    waveform,
                    put_item=put_item,
                    is_cancelled=is_cancelled,
                    stream_state=stream_state,
                )
            return emitted

        text_chunks = self._prepare_runtime_text_chunks(text, voice=voice)
        if not text_chunks:
            return 0

        emitted = 0
        for chunk_index, chunk_text in enumerate(text_chunks):
            if is_cancelled():
                raise _MossStreamCancelled()
            pending_decode_frames: list[list[int]] = []
            chunk_emitted = 0
            generated_frames: list[list[int]] = []
            t0 = time.monotonic()
            self._runtime.codec_streaming_session.reset()

            def decode_pending(force: bool) -> None:
                nonlocal chunk_emitted, emitted
                pending_count = len(pending_decode_frames)
                if pending_count <= 0:
                    return
                decode_budget = self._resolve_stream_decode_frame_budget(
                    int(stream_state["emitted_samples_total"]),
                    self.sample_rate,
                    stream_state["first_audio_emitted_at_perf"],
                )
                if not force and pending_count < max(1, decode_budget):
                    return
                frame_budget = pending_count if force else min(pending_count, max(1, decode_budget))
                frame_chunk = pending_decode_frames[:frame_budget]
                del pending_decode_frames[:frame_budget]
                decoded = self._runtime.codec_streaming_session.run_frames(frame_chunk)
                if decoded is None:
                    return
                audio, audio_length = decoded
                if audio_length <= 0:
                    return
                waveform = self._merge_codec_audio(audio, int(audio_length))
                count = self._emit_stream_waveform(
                    waveform,
                    put_item=put_item,
                    is_cancelled=is_cancelled,
                    stream_state=stream_state,
                    edge_fade=False,
                )
                chunk_emitted += count
                emitted += count

            def on_frame(_generated_frames: list[list[int]], _step_index: int, frame: list[int]) -> None:
                if is_cancelled():
                    raise _MossStreamCancelled()
                pending_decode_frames.append(list(frame))
                decode_pending(False)

            try:
                text_token_ids = self._runtime.encode_text(chunk_text)
                request_rows = self._runtime.build_voice_clone_request_rows(prompt_audio_codes, text_token_ids)
                generated_frames = self._runtime.generate_audio_frames(request_rows, on_frame=on_frame)
                decode_pending(True)
            finally:
                self._runtime.codec_streaming_session.reset()

            logger.info(
                "MOSS 运行时小块 %d/%d 已流式输出（%.1fs，帧=%d，音频块=%d）",
                chunk_index + 1,
                len(text_chunks),
                time.monotonic() - t0,
                len(generated_frames),
                chunk_emitted,
            )
            if chunk_index < len(text_chunks) - 1:
                pause_seconds = self._runtime_pause_seconds(chunk_text)
                silence = self._silence_array(pause_seconds)
                if silence.size:
                    emitted += self._emit_stream_waveform(
                        silence,
                        put_item=put_item,
                        is_cancelled=is_cancelled,
                        stream_state=stream_state,
                        is_pause=True,
                    )
        return emitted

    def _resolve_stream_decode_frame_budget(
        self,
        emitted_samples_total: int,
        sample_rate: int,
        first_audio_emitted_at_perf: float | None,
    ) -> int:
        thresholds = StreamBudgetThresholds(
            low=float(getattr(self.config, "moss_stream_budget_threshold_low", 0.25)),
            mid=float(getattr(self.config, "moss_stream_budget_threshold_mid", 0.65)),
            high=float(getattr(self.config, "moss_stream_budget_threshold_high", 1.20)),
        )
        return resolve_stream_decode_frame_budget(
            emitted_samples_total,
            sample_rate,
            first_audio_emitted_at_perf,
            thresholds,
        )

    def _runtime_supports_frame_streaming(self) -> bool:
        return runtime_supports_frame_streaming(self._runtime)

    def _merge_codec_audio(self, audio, audio_length: int):
        return merge_codec_audio(audio, audio_length, channels=self.channels)

    def _emit_stream_waveform(
        self,
        waveform,
        *,
        put_item: Callable[[tuple[str, object]], bool],
        is_cancelled: Callable[[], bool],
        stream_state: dict,
        is_pause: bool = False,
        edge_fade: bool = True,
    ) -> int:
        if is_cancelled():
            raise _MossStreamCancelled()
        processed = self._postprocess_waveform(
            waveform,
            update_quality=not is_pause,
            edge_fade=edge_fade and not is_pause,
            compress_silence=not is_pause,
        )
        if not is_pause and stream_state["first_audio_emitted_at_perf"] is None and getattr(processed, "size", 0):
            stream_state["first_audio_emitted_at_perf"] = time.perf_counter()
        stream_state["emitted_samples_total"] = int(stream_state["emitted_samples_total"]) + int(processed.shape[0])
        emitted = 0
        for piece in self._split_waveform_for_stream(processed, chunk_seconds=stream_state.get("chunk_seconds")):
            if is_cancelled() or not put_item(("audio", piece)):
                raise _MossStreamCancelled()
            emitted += 1
        return emitted

    def _stream_chunk_seconds_for_text(self) -> float:
        base = float(self.config.moss_stream_chunk_seconds)
        return max(0.05, min(2.0, base))

    def _split_waveform_for_stream(self, waveform, *, chunk_seconds: float | None = None):
        return split_waveform_for_stream(
            waveform,
            sample_rate=self.sample_rate,
            chunk_seconds=float(chunk_seconds or self.config.moss_stream_chunk_seconds),
            min_floor=float(getattr(self.config, "moss_stream_chunk_min_floor", 0.10)),
        )
