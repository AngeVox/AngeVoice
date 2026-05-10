"""MOSS-TTS-Nano 引擎适配器。

官方推理 runtime 仍由 OpenMOSS 提供；本文件只负责把 runtime 接入
AngeVoice 的引擎接口。纯逻辑已拆到 ``kokoro_tts.moss`` 子包。
"""

from __future__ import annotations

import base64
import concurrent.futures
import gc
import logging
import queue
import time
import threading
from collections import OrderedDict
from typing import Callable, Optional

from .audio import encode_audio_segment, write_wav_bytes
from .config import TTSConfig
from .moss import (
    StreamBudgetThresholds,
    analyze_waveform,
    clean_text as moss_clean_text,
    concat_waveforms,
    create_runtime as create_moss_runtime,
    ensure_import_path,
    merge_codec_audio,
    normalize_waveform,
    prompt_audio_cache_key,
    prepare_prompt_audio,
    MossProcessClient,
    MossProcessTimeoutError,
    resolve_prompt_audio_codes_cached,
    resolve_stream_decode_frame_budget,
    runtime_supports_frame_streaming,
    segment_text as moss_segment_text,
    silence_array,
    split_waveform_for_stream,
    temp_output_path,
)

logger = logging.getLogger(__name__)

# 拼接多个文本段时插入的静音时长（秒）
_SEGMENT_SILENCE_SECONDS = 0.08


class _MossStreamCancelled(Exception):
    """客户端取消 MOSS 流式请求时使用的内部异常。"""


class MossNanoEngine:
    """OpenMOSS 官方 ONNX runtime 的 AngeVoice 适配器。"""

    SUPPORTED_STREAM_FORMATS = {"pcm_s16le", "wav"}
    _provider_patch_lock = threading.Lock()

    def __init__(
        self,
        config: TTSConfig,
        execution_provider: str = "cpu",
        engine_id: str = "moss-nano",
        process_isolation: bool | None = None,
    ):
        self.config = config
        self.execution_provider = str(execution_provider or "cpu").lower()
        self.engine_id = engine_id
        self.display_name = "MOSS-TTS-Nano"
        self._process_isolated = self._resolve_process_isolation(process_isolation)
        self._process_client: MossProcessClient | None = None
        self._cached_sample_rate = 48000
        self._cached_channels = 2
        self._cached_voices: list[str] = [self.config.moss_default_voice]
        self._runtime = None
        self._loaded = False
        self._actual_provider = self.execution_provider
        self._load_error = ""
        self._self_test = None
        self._last_output_quality = None
        self._runtime_lock = threading.Lock()
        self._prompt_cache_lock = threading.Lock()
        self._prompt_audio_code_cache: OrderedDict[str, list[list[int]]] = OrderedDict()
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"{engine_id}-worker")
        self._unhealthy = False
        self._executor_lock = threading.Lock()
        self._consecutive_timeouts = 0


    def _resolve_process_isolation(self, explicit: bool | None) -> bool:
        """判断当前 MOSS 引擎是否启用进程级隔离。"""

        if explicit is not None:
            return bool(explicit)
        if not bool(getattr(self.config, "moss_process_isolation_enabled", True)):
            return False
        providers = {
            item.strip().lower()
            for item in str(getattr(self.config, "moss_process_isolation_providers", "cuda")).split(",")
            if item.strip()
        }
        return self.execution_provider in providers

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def is_healthy(self) -> bool:
        return self._loaded and not self._unhealthy

    @property
    def sample_rate(self) -> int:
        if self._runtime is None:
            return int(self._cached_sample_rate)
        return int(self._runtime.codec_meta["codec_config"]["sample_rate"])

    @property
    def channels(self) -> int:
        if self._runtime is None:
            return int(self._cached_channels)
        return int(self._runtime.codec_meta["codec_config"]["channels"])

    @property
    def device(self) -> str:
        return self._actual_provider

    @property
    def default_voice(self) -> str:
        return self.config.moss_default_voice

    def get_voices(self) -> list[str]:
        if self._process_isolated and self._process_client is not None and self._process_client.alive:
            try:
                voices = self._process_client.request("voices", {}, timeout=10.0)
                self._cached_voices = [str(item) for item in voices] or [self.default_voice]
            except Exception:
                logger.debug("读取 MOSS 隔离进程音色列表失败", exc_info=True)
            return list(self._cached_voices)
        if self._runtime is None:
            return list(self._cached_voices or [self.default_voice])
        try:
            self._cached_voices = [str(item["voice"]) for item in self._runtime.list_builtin_voices()]
            return list(self._cached_voices)
        except Exception:
            logger.debug("读取 MOSS 音色列表失败", exc_info=True)
            return [self.default_voice]

    def metadata(self) -> dict:
        return {
            "id": self.engine_id,
            "name": self.display_name,
            "backend": "moss-tts-nano-onnx",
            "loaded": self.is_loaded,
            "device": self.device,
            "requested_provider": self.execution_provider,
            "actual_provider": self._actual_provider,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "voices": self.get_voices(),
            "default_voice": self.default_voice,
            "modes": ["preset_voice", "voice_clone"],
            "voice_clone_supported": True,
            "voice_clone_enabled": True,
            "prompt_audio_path": str(self.config.moss_prompt_audio_path) if self.config.moss_prompt_audio_path else "",
            "streaming": True,
            "stream_chunk_seconds": self.config.moss_stream_chunk_seconds,
            "stream_queue_max_items": self.config.moss_stream_queue_max_items,
            "speed_supported": False,
            "text_rules_enabled": bool(self.config.moss_apply_angevoice_rules),
            "experimental": self.execution_provider == "cuda",
            "error": self._load_error,
            "self_test": self._self_test,
            "last_output_quality": self._last_output_quality,
            "prompt_audio_max_seconds": self.config.moss_prompt_audio_max_seconds,
            "output_target_peak": self.config.moss_output_target_peak,
            "sample_mode": self.config.moss_sample_mode,
            "seed": self.config.moss_seed,
            "cuda_memory_limit_mb": self.config.moss_cuda_memory_limit_mb,
            "healthy": self.is_healthy,
            "unhealthy": self._unhealthy,
            "consecutive_timeouts": self._consecutive_timeouts,
            "process_isolated": self._process_isolated,
            "process_alive": bool(self._process_client and self._process_client.alive),
        }

    def load(self) -> "MossNanoEngine":
        if self._loaded:
            return self

        if self._process_isolated:
            return self._load_process_isolated()

        self._ensure_import_path()
        try:
            self._runtime = self._create_runtime(self.execution_provider)
            self._actual_provider = self.execution_provider
            self._run_self_test_if_needed()
        except Exception as exc:
            if self.execution_provider != "cuda" or not self.config.moss_auto_fallback_cpu:
                self._load_error = str(exc)
                raise
            logger.warning("MOSS CUDA load/self-test failed, falling back to CPU: %s", exc)
            fallback_reason = str(exc)
            self.unload()
            self._runtime = self._create_runtime("cpu")
            self._actual_provider = "cpu"
            if self.config.moss_quality_gate_enabled:
                self._run_cpu_fallback_quality_gate(fallback_reason)
            else:
                self._self_test = {"ok": True, "fallback_from": "cuda", "reason": fallback_reason}

        self._loaded = True
        logger.info("MOSS-TTS-Nano loaded (requested=%s actual=%s)", self.execution_provider, self._actual_provider)
        return self


    def _load_process_isolated(self) -> "MossNanoEngine":
        """在独立子进程中加载 MOSS runtime。"""

        self._process_client = MossProcessClient(
            config=self.config,
            provider=self.execution_provider,
            engine_id=self.engine_id,
            logger=logger,
        )
        try:
            metadata = self._process_client.request("load", {}, timeout=float(self.config.request_timeout_seconds))
        except Exception as exc:
            self._load_error = str(exc)
            self._process_client.close(kill=True)
            self._process_client = None
            raise
        self._runtime = None
        self._loaded = True
        self._unhealthy = False
        self._actual_provider = str(metadata.get("actual_provider") or self.execution_provider) if isinstance(metadata, dict) else self.execution_provider
        self._cached_sample_rate = int(metadata.get("sample_rate") or 48000) if isinstance(metadata, dict) else 48000
        self._cached_channels = int(metadata.get("channels") or 2) if isinstance(metadata, dict) else 2
        voices = metadata.get("voices") if isinstance(metadata, dict) else None
        if voices:
            self._cached_voices = [str(item) for item in voices]
        self._self_test = metadata.get("self_test") if isinstance(metadata, dict) else None
        self._last_output_quality = metadata.get("last_output_quality") if isinstance(metadata, dict) else None
        logger.info("MOSS-TTS-Nano loaded in isolated process (requested=%s actual=%s)", self.execution_provider, self._actual_provider)
        return self

    def _rebuild_executor(self) -> None:
        """重建单 worker 线程池，隔离已经超时或可能卡死的推理任务。"""
        with self._executor_lock:
            old = self._executor
            self._executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix=f"{self.engine_id}-worker",
            )
        try:
            old.shutdown(wait=False)
        except Exception:
            logger.debug("Failed to shut down old executor", exc_info=True)

    def unload(self) -> None:
        if self._process_client is not None:
            self._process_client.close(kill=False)
            self._process_client = None
        with self._runtime_lock:
            self._runtime = None
            self._loaded = False
            self._unhealthy = False
            self._consecutive_timeouts = 0
            with self._prompt_cache_lock:
                self._prompt_audio_code_cache.clear()
        self._rebuild_executor()
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            logger.debug("MOSS CUDA cache cleanup skipped", exc_info=True)

    def synthesize(self, text: str, voice: str = "", speed: float = 1.0, prompt_audio_path: str | None = None) -> bytes:
        waveform = self.synthesize_array(text=text, voice=voice, speed=speed, prompt_audio_path=prompt_audio_path)
        return write_wav_bytes(waveform, self.sample_rate)

    def synthesize_array(self, text: str, voice: str = "", speed: float = 1.0, prompt_audio_path: str | None = None):
        self._validate_request(text=text, voice=voice, speed=speed)
        prepared_text = self._clean_text(text)
        segments = self._segment_text(prepared_text)
        prompt_audio = prompt_audio_path or (
            str(self.config.moss_prompt_audio_path) if self.config.moss_prompt_audio_path else None
        )
        timeout = self.config.request_timeout_seconds

        if self._process_isolated:
            return self._synthesize_array_process_isolated(
                text=text,
                voice=voice,
                speed=speed,
                prompt_audio_path=prompt_audio,
                timeout=timeout,
            )

        logger.info("MOSS synthesize: segments=%d, voice=%s", len(segments), voice or self.default_voice)

        def _run():
            with self._runtime_lock:
                return self._concat_waveforms(
                    list(self._iter_waveforms(segments=segments, voice=voice, prompt_audio_path=prompt_audio))
                )

        future = self._executor.submit(_run)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            future.cancel()
            self._consecutive_timeouts += 1
            self._unhealthy = True
            self._rebuild_executor()
            logger.warning(
                "MOSS inference timed out (%.0fs) — executor rebuilt, engine marked unhealthy (consecutive=%d)",
                timeout, self._consecutive_timeouts,
            )
            raise RuntimeError(
                f"MOSS inference timed out ({timeout}s). "
                "Engine marked unhealthy and executor rebuilt. "
                "The next request will trigger a full reload. "
                "If this persists, try switching to CPU or restarting the container."
            )


    def _synthesize_array_process_isolated(self, *, text: str, voice: str, speed: float, prompt_audio_path: str | None, timeout: float):
        """通过隔离子进程执行一次非流式 MOSS 推理。"""

        if self._process_client is None:
            self.load()
        try:
            return self._process_client.request(
                "synthesize_array",
                {"text": text, "voice": voice, "speed": speed, "prompt_audio_path": prompt_audio_path},
                timeout=float(timeout),
            )
        except MossProcessTimeoutError as exc:
            self._mark_process_failure(timeout=timeout, reason="timeout")
            raise RuntimeError(
                f"MOSS isolated worker timed out ({timeout}s). Worker process was killed and will be rebuilt on next request."
            ) from exc
        except Exception:
            self._mark_process_failure(timeout=timeout, reason="worker_error")
            raise

    def _mark_process_failure(self, *, timeout: float, reason: str) -> None:
        """记录隔离进程失败并让下次请求重新加载 worker。"""

        self._consecutive_timeouts += 1
        self._unhealthy = True
        self._loaded = False
        if self._process_client is not None:
            self._process_client.close(kill=True)
            self._process_client = None
        logger.warning("MOSS isolated worker failed (%s, %.0fs); process killed (consecutive=%d)", reason, timeout, self._consecutive_timeouts)

    def synthesize_stream(
        self,
        text,
        voice="",
        speed=1.0,
        fmt="pcm_s16le",
        prompt_audio_path: str | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ):
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

        if self._process_client is None:
            self.load()
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
            ):
                if cancel_check is not None:
                    try:
                        if bool(cancel_check()):
                            if self._process_client is not None:
                                self._process_client.close(kill=True)
                                self._process_client = None
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

    def _iter_waveforms(self, *, segments: list[str], voice: str = "", prompt_audio_path: str | None = None):
        prompt_audio_codes = self._resolve_prompt_audio_codes_cached(voice=voice, prompt_audio_path=prompt_audio_path)
        self._configure_runtime_generation()
        total_segments = len([item for item in segments if item.strip()])
        emitted = 0
        for seg in segments:
            if not seg.strip():
                continue
            emitted += 1
            t0 = time.monotonic()
            for waveform in self._iter_runtime_chunks(seg, voice=voice, prompt_audio_codes=prompt_audio_codes):
                processed = self._postprocess_waveform(waveform)
                logger.info(
                    "MOSS segment %d/%d chunk done (%.1fs, %d samples)",
                    emitted,
                    total_segments,
                    time.monotonic() - t0,
                    processed.shape[0],
                )
                yield processed
            if emitted < total_segments:
                silence = self._silence_array(_SEGMENT_SILENCE_SECONDS)
                if silence.size:
                    yield silence

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
                silence = self._silence_array(_SEGMENT_SILENCE_SECONDS)
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
                pause_seconds = float(self._runtime.estimate_voice_clone_inter_chunk_pause_seconds(chunk_text))
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

    def _iter_runtime_chunks(self, text: str, *, voice: str = "", prompt_audio_codes: list[list[int]]):
        import numpy as np

        text_chunks = self._prepare_runtime_text_chunks(text, voice=voice)
        if not text_chunks:
            return
        for chunk_index, chunk_text in enumerate(text_chunks):
            chunk_result = self._runtime.synthesize_single_chunk(
                text=chunk_text,
                prompt_audio_codes=prompt_audio_codes,
                streaming=bool(self.config.moss_realtime_streaming_decode),
            )
            yield np.asarray(chunk_result["waveform"], dtype=np.float32)
            if chunk_index < len(text_chunks) - 1:
                pause_seconds = float(self._runtime.estimate_voice_clone_inter_chunk_pause_seconds(chunk_text))
                silence = self._silence_array(pause_seconds)
                if silence.size:
                    yield silence

    def _prepare_runtime_text_chunks(self, text: str, *, voice: str = "") -> list[str]:
        prepared_texts = self._runtime.prepare_synthesis_text(
            text=text,
            voice=voice or self.default_voice,
            enable_wetext=bool(self.config.moss_enable_wetext_processing),
            enable_normalize_tts_text=bool(self.config.moss_enable_normalize_tts_text),
        )
        prepared_text = str(prepared_texts["text"])
        return list(
            self._runtime.split_voice_clone_text(
                prepared_text,
                max_tokens=int(self.config.moss_voice_clone_max_text_tokens),
            )
        )

    def _configure_runtime_generation(self) -> None:
        generation = self._runtime.manifest["generation_defaults"]
        generation["max_new_frames"] = int(self.config.moss_max_new_frames)
        generation["sample_mode"] = self.config.moss_sample_mode
        generation["do_sample"] = self.config.moss_sample_mode != "greedy"
        seed = int(self.config.moss_seed)
        if seed >= 0:
            try:
                import numpy as np

                self._runtime.rng = np.random.default_rng(seed)
            except Exception:
                logger.debug("Failed to reset MOSS RNG seed", exc_info=True)

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
    ) -> int:
        if is_cancelled():
            raise _MossStreamCancelled()
        processed = self._postprocess_waveform(waveform, update_quality=not is_pause)
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

    def _concat_waveforms(self, waveforms: list):
        return concat_waveforms(waveforms)

    def _silence_array(self, seconds: float):
        return silence_array(seconds, sample_rate=self.sample_rate, channels=self.channels)

    def _resolve_prompt_audio_codes_cached(self, *, voice: str = "", prompt_audio_path: str | None = None) -> list[list[int]]:
        return resolve_prompt_audio_codes_cached(
            runtime=self._runtime,
            cache=self._prompt_audio_code_cache,
            cache_lock=self._prompt_cache_lock,
            voice=voice,
            default_voice=self.default_voice,
            prompt_audio_path=prompt_audio_path,
            max_items=int(self.config.moss_prompt_cache_max_items),
            max_seconds=float(self.config.moss_prompt_audio_max_seconds),
            sample_rate=self.sample_rate,
            channels=self.channels,
            logger=logger,
        )

    def _prompt_audio_cache_key(self, *, voice: str = "", prompt_audio_path: str | None = None) -> str:
        return prompt_audio_cache_key(
            voice=voice,
            default_voice=self.default_voice,
            prompt_audio_path=prompt_audio_path,
            max_seconds=float(self.config.moss_prompt_audio_max_seconds),
            sample_rate=self.sample_rate,
            channels=self.channels,
        )

    def _prepare_prompt_audio(self, prompt_audio_path: str | None) -> tuple[str | None, str | None]:
        return prepare_prompt_audio(
            prompt_audio_path,
            max_seconds=float(self.config.moss_prompt_audio_max_seconds),
            sample_rate=self.sample_rate,
            channels=self.channels,
            logger=logger,
        )

    def _postprocess_waveform(self, waveform, *, update_quality: bool = True):
        processed, quality = normalize_waveform(
            waveform,
            channels=self.channels,
            gain=float(self.config.moss_output_gain),
            target_peak=float(self.config.moss_output_target_peak),
            peak_normalize_enabled=bool(self.config.moss_output_peak_normalize_enabled),
        )
        if update_quality:
            self._last_output_quality = quality.as_dict()
        return processed

    def _ensure_import_path(self) -> None:
        ensure_import_path(self.config.moss_repo_path)

    def _create_runtime(self, provider: str):
        return create_moss_runtime(
            config=self.config,
            provider=provider,
            provider_patch_lock=self._provider_patch_lock,
            logger=logger,
        )

    def _run_self_test_if_needed(self) -> None:
        if self._runtime is None:
            return
        if self.execution_provider != "cuda" and not self.config.moss_quality_gate_enabled:
            return
        if self.execution_provider == "cuda" and self.config.moss_cuda_self_test_enabled:
            self._runtime.warmup()
        if not self.config.moss_quality_gate_enabled:
            self._self_test = {"ok": True, "mode": "warmup"}
            return
        result = self._runtime.synthesize(
            text="你好，AngeVoice 正在进行模型自检。",
            voice=self.default_voice,
            prompt_audio_path=str(self.config.moss_prompt_audio_path) if self.config.moss_prompt_audio_path else None,
            output_audio_path=self._temp_output_path(),
            sample_mode="greedy",
            do_sample=False,
            streaming=True,
            max_new_frames=min(96, int(self.config.moss_max_new_frames)),
            voice_clone_max_text_tokens=min(40, int(self.config.moss_voice_clone_max_text_tokens)),
            enable_wetext=False,
            enable_normalize_tts_text=True,
        )
        self._self_test = self._analyze_waveform(result["waveform"], int(result["sample_rate"]))
        if not self._self_test["ok"]:
            raise RuntimeError("MOSS quality gate failed: " + self._self_test["reason"])

    def _run_cpu_fallback_quality_gate(self, fallback_reason: str) -> None:
        result = self._runtime.synthesize(
            text="你好，AngeVoice 正在验证 CPU 回退模型。",
            voice=self.default_voice,
            prompt_audio_path=str(self.config.moss_prompt_audio_path) if self.config.moss_prompt_audio_path else None,
            output_audio_path=self._temp_output_path(),
            sample_mode="greedy",
            do_sample=False,
            streaming=True,
            max_new_frames=min(96, int(self.config.moss_max_new_frames)),
            voice_clone_max_text_tokens=min(40, int(self.config.moss_voice_clone_max_text_tokens)),
            enable_wetext=False,
            enable_normalize_tts_text=True,
        )
        self._self_test = self._analyze_waveform(result["waveform"], int(result["sample_rate"]))
        self._self_test.update({"fallback_from": "cuda", "fallback_reason": fallback_reason})
        if not self._self_test["ok"]:
            raise RuntimeError("MOSS CPU fallback quality gate failed: " + self._self_test["reason"])

    def _analyze_waveform(self, waveform, sample_rate: int) -> dict:
        return analyze_waveform(
            waveform,
            sample_rate,
            max_clip_ratio=float(self.config.moss_max_clip_ratio),
        )

    def _validate_request(self, text: str, voice: str, speed: float) -> None:
        if not self._loaded or (self._runtime is None and not self._process_isolated):
            raise RuntimeError("MOSS 引擎未加载，请先加载模型")
        if not text or not str(text).strip():
            raise ValueError("文本不能为空")
        if len(text) > self.config.max_text_length:
            raise ValueError(f"文本过长 ({len(text)} 字符)，上限 {self.config.max_text_length}")
        try:
            float(speed)
        except (TypeError, ValueError):
            raise ValueError("speed 必须是数字") from None

    def _clean_text(self, text: str) -> str:
        return moss_clean_text(text, apply_angevoice_rules=bool(self.config.moss_apply_angevoice_rules))

    def _segment_text(self, text: str) -> list[str]:
        return moss_segment_text(
            text,
            max_text_length=int(self.config.max_text_length),
            segment_length=int(self.config.segment_length),
        )

    def _temp_output_path(self) -> str:
        return temp_output_path()

