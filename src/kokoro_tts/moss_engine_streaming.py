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
from .moss import (
    MossProcessTimeoutError,
    StreamBudgetThresholds,
    merge_codec_audio,
    resolve_stream_decode_frame_budget,
    runtime_supports_frame_streaming,
    split_waveform_for_stream,
)

logger = logging.getLogger(__name__)

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
            yield {"type": "error", "message": f"Unsupported format: {fmt}"}
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
                logger.debug("MOSS cancel_check failed", exc_info=True)
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
                logger.info("MOSS stream cancelled")
            except Exception as exc:
                logger.warning("MOSS stream failed: %s", exc)
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
                            logger.warning("MOSS stream worker failed: %s", exc)
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
        """通过隔离子进程执行 MOSS 流式推理。"""

        if self._process_client is None or not self._process_client.alive:
            self._loaded = False
            self.load()
        if self._process_client is None:
            # 加载可能已被测试或外层取消路径取消/替换。
            yield {"type": "done", "total_segments": 0, "total_audio_chunks": 0}
            return
        try:
            for event in self._process_client.stream(
                "synthesize_stream",
                {
                    "text": text,
                    "voice": voice,
                    "speed": speed,
                    "fmt": fmt,
                    "prompt_audio_path": prompt_audio_path,
                    # 跨进程不能传递 cancel_check，父进程会在外层检测取消。
                    "cancel_check": None,
                },
                timeout=float(self.config.request_timeout_seconds),
                cancel_check=cancel_check,
            ):
                if cancel_check is not None:
                    try:
                        if bool(cancel_check()):
                            if self._process_client is not None:
                                self._process_client.close(kill=True)
                                self._process_client = None
                            # 用户取消不是 runtime 故障，但 worker 已被杀掉，下一次请求需要重载。
                            self._loaded = False
                            break
                    except Exception:
                        logger.debug("MOSS 隔离流式 cancel_check 失败", exc_info=True)
                yield event
        except MossProcessTimeoutError as exc:
            self._mark_process_failure(timeout=float(self.config.request_timeout_seconds), reason="stream_timeout")
            yield {"type": "segment_error", "index": 0, "message": str(exc), "model": self.engine_id}
            yield {"type": "done", "total_segments": 0, "total_audio_chunks": 0}
        except Exception as exc:
            self._mark_process_failure(timeout=float(self.config.request_timeout_seconds), reason="stream_error")
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
        stream_state = {"emitted_samples_total": 0, "first_audio_emitted_at_perf": None}
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
                "MOSS segment %d/%d streamed (%.1fs, audio chunks=%d)",
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
                "MOSS runtime chunk %d/%d streamed (%.1fs, frames=%d, audio chunks=%d)",
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
        for piece in self._split_waveform_for_stream(processed):
            if is_cancelled() or not put_item(("audio", piece)):
                raise _MossStreamCancelled()
            emitted += 1
        return emitted

    def _split_waveform_for_stream(self, waveform):
        return split_waveform_for_stream(
            waveform,
            sample_rate=self.sample_rate,
            chunk_seconds=float(self.config.moss_stream_chunk_seconds),
            min_floor=float(getattr(self.config, "moss_stream_chunk_min_floor", 0.10)),
        )


