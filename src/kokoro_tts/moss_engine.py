"""MOSS-TTS-Nano adapter for AngeVoice.

The inference runtime itself stays in the official OpenMOSS package/repository.
This module only adapts that runtime to AngeVoice's engine interface.
"""

from __future__ import annotations

import base64
import concurrent.futures
import gc
import hashlib
import logging
import queue
import sys
import tempfile
import time
import threading
from collections import OrderedDict
from contextlib import suppress
from pathlib import Path
from typing import Callable, Optional

from .audio import encode_audio_segment, normalize_audio_array, write_wav_bytes
from .config import TTSConfig
from .engine import normalize_text_for_tts

logger = logging.getLogger(__name__)

# Silence between concatenated segments (seconds)
_SEGMENT_SILENCE_SECONDS = 0.08


class _MossStreamCancelled(Exception):
    """Raised internally when the client cancels an active MOSS stream."""


class MossNanoEngine:
    """Adapter around OpenMOSS' official ONNX runtime."""

    SUPPORTED_STREAM_FORMATS = {"pcm_s16le", "wav"}
    _provider_patch_lock = threading.Lock()

    def __init__(self, config: TTSConfig, execution_provider: str = "cpu", engine_id: str = "moss-nano"):
        self.config = config
        self.execution_provider = str(execution_provider or "cpu").lower()
        self.engine_id = engine_id
        self.display_name = "MOSS-TTS-Nano"
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

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def is_healthy(self) -> bool:
        return self._loaded and not self._unhealthy

    @property
    def sample_rate(self) -> int:
        if self._runtime is None:
            return 48000
        return int(self._runtime.codec_meta["codec_config"]["sample_rate"])

    @property
    def channels(self) -> int:
        if self._runtime is None:
            return 2
        return int(self._runtime.codec_meta["codec_config"]["channels"])

    @property
    def device(self) -> str:
        return self._actual_provider

    @property
    def default_voice(self) -> str:
        return self.config.moss_default_voice

    def get_voices(self) -> list[str]:
        if self._runtime is None:
            return [self.default_voice]
        try:
            return [str(item["voice"]) for item in self._runtime.list_builtin_voices()]
        except Exception:
            logger.debug("Failed to list MOSS voices", exc_info=True)
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
        }

    def load(self) -> "MossNanoEngine":
        if self._loaded:
            return self

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

    def _rebuild_executor(self) -> None:
        """Shutdown the current executor and create a fresh one.

        Called after a timeout to discard a potentially stuck worker thread.
        The old executor is shut down with ``wait=False`` so that a genuinely
        stuck CUDA kernel is left to die in the background while the new
        executor can accept work immediately.
        """
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
        try:
            from ort_cpu_runtime import _resolve_stream_decode_frame_budget

            return int(_resolve_stream_decode_frame_budget(emitted_samples_total, sample_rate, first_audio_emitted_at_perf))
        except Exception:
            if not first_audio_emitted_at_perf:
                return 1
            lead_seconds = (emitted_samples_total / float(sample_rate or 1)) - max(
                0.0,
                time.perf_counter() - float(first_audio_emitted_at_perf),
            )
            threshold_low = float(getattr(self.config, "moss_stream_budget_threshold_low", 0.20))
            threshold_mid = float(getattr(self.config, "moss_stream_budget_threshold_mid", 0.55))
            threshold_high = float(getattr(self.config, "moss_stream_budget_threshold_high", 1.10))
            if lead_seconds < threshold_low:
                return 1
            if lead_seconds < threshold_mid:
                return 2
            if lead_seconds < threshold_high:
                return 4
            return 8

    def _runtime_supports_frame_streaming(self) -> bool:
        return (
            self._runtime is not None
            and hasattr(self._runtime, "generate_audio_frames")
            and hasattr(self._runtime, "codec_streaming_session")
            and hasattr(self._runtime, "encode_text")
            and hasattr(self._runtime, "build_voice_clone_request_rows")
        )

    def _merge_codec_audio(self, audio, audio_length: int):
        import numpy as np

        raw = np.asarray(audio, dtype=np.float32)
        if raw.ndim < 3 or audio_length <= 0:
            return np.zeros((0, self.channels), dtype=np.float32)
        channel_count = int(raw.shape[1])
        channel_arrays = [
            np.asarray(raw[0, channel_index, :audio_length], dtype=np.float32)
            for channel_index in range(channel_count)
        ]
        if not channel_arrays:
            return np.zeros((0, self.channels), dtype=np.float32)
        return np.stack(channel_arrays, axis=1)

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
        import numpy as np

        audio = np.asarray(waveform, dtype=np.float32)
        if audio.size == 0:
            return
        min_floor = float(getattr(self.config, "moss_stream_chunk_min_floor", 0.05))
        max_seconds = max(min_floor, float(self.config.moss_stream_chunk_seconds))
        max_samples = max(1, int(self.sample_rate * max_seconds))
        total_samples = int(audio.shape[0])
        for start in range(0, total_samples, max_samples):
            yield np.ascontiguousarray(audio[start : start + max_samples])

    def _concat_waveforms(self, waveforms: list):
        import numpy as np

        parts = [item for item in waveforms if getattr(item, "size", 0)]
        if not parts:
            raise RuntimeError("MOSS: all segments produced empty audio")
        return np.concatenate(parts)

    def _silence_array(self, seconds: float):
        import numpy as np

        samples = max(0, int(self.sample_rate * max(0.0, float(seconds))))
        if samples <= 0:
            return np.zeros((0, self.channels), dtype=np.float32)
        return np.zeros((samples, self.channels), dtype=np.float32)

    def _resolve_prompt_audio_codes_cached(self, *, voice: str = "", prompt_audio_path: str | None = None) -> list[list[int]]:
        key = self._prompt_audio_cache_key(voice=voice, prompt_audio_path=prompt_audio_path)
        with self._prompt_cache_lock:
            cached = self._prompt_audio_code_cache.get(key)
            if cached is not None:
                self._prompt_audio_code_cache.move_to_end(key)
                return cached

        prepared_path, cleanup_path = self._prepare_prompt_audio(prompt_audio_path)
        try:
            codes = self._runtime.resolve_prompt_audio_codes(
                voice=voice or self.default_voice,
                prompt_audio_path=prepared_path,
            )
        finally:
            if cleanup_path:
                with suppress(OSError):
                    Path(cleanup_path).unlink()

        max_items = int(self.config.moss_prompt_cache_max_items)
        if max_items > 0:
            with self._prompt_cache_lock:
                self._prompt_audio_code_cache[key] = codes
                self._prompt_audio_code_cache.move_to_end(key)
                while len(self._prompt_audio_code_cache) > max_items:
                    self._prompt_audio_code_cache.popitem(last=False)
        return codes

    def _prompt_audio_cache_key(self, *, voice: str = "", prompt_audio_path: str | None = None) -> str:
        if not prompt_audio_path:
            return f"voice:{voice or self.default_voice}"
        path = Path(prompt_audio_path).expanduser()
        digest = hashlib.sha256()
        try:
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError:
            digest.update(str(path).encode("utf-8", "ignore"))
        return (
            f"prompt:{digest.hexdigest()}:"
            f"voice:{voice or self.default_voice}:"
            f"maxsec:{float(self.config.moss_prompt_audio_max_seconds):.3f}:"
            f"sr:{self.sample_rate}:ch:{self.channels}"
        )

    def _prepare_prompt_audio(self, prompt_audio_path: str | None) -> tuple[str | None, str | None]:
        if not prompt_audio_path:
            return None, None
        max_seconds = float(self.config.moss_prompt_audio_max_seconds or 0)
        if max_seconds <= 0:
            return prompt_audio_path, None
        try:
            import torch
            import torchaudio
        except Exception:
            logger.debug("torchaudio unavailable; using original prompt audio", exc_info=True)
            return prompt_audio_path, None

        source = Path(prompt_audio_path).expanduser().resolve()
        try:
            waveform, sample_rate = torchaudio.load(str(source))
        except Exception:
            logger.debug("Failed to load prompt audio for trimming; using original", exc_info=True)
            return prompt_audio_path, None

        target_sr = self.sample_rate
        waveform = waveform.to(torch.float32)
        if sample_rate != target_sr:
            waveform = torchaudio.functional.resample(waveform, sample_rate, target_sr)
        max_samples = int(target_sr * max_seconds)
        if max_samples > 0 and int(waveform.shape[-1]) > max_samples:
            logger.info(
                "Trimming MOSS prompt audio from %.2fs to %.2fs",
                float(waveform.shape[-1]) / float(target_sr),
                max_seconds,
            )
            waveform = waveform[..., :max_samples]
        if int(waveform.shape[0]) > self.channels:
            waveform = waveform.mean(dim=0, keepdim=True)
        if int(waveform.shape[0]) < self.channels:
            waveform = waveform.repeat(self.channels, 1)
        waveform = torch.clamp(waveform, -1.0, 1.0)
        temp_dir = Path(tempfile.gettempdir()) / "angevoice_moss_prompt"
        temp_dir.mkdir(parents=True, exist_ok=True)
        target = temp_dir / f"{source.stem}_{hashlib.sha1(str(source).encode()).hexdigest()[:10]}_{int(max_seconds * 1000)}ms.wav"
        torchaudio.save(str(target), waveform.cpu(), target_sr)
        return str(target), str(target)

    def _postprocess_waveform(self, waveform, *, update_quality: bool = True):
        import numpy as np

        audio = np.asarray(waveform, dtype=np.float32)
        if audio.ndim == 0:
            audio = audio.reshape(1)
        elif audio.ndim > 2:
            audio = audio.reshape(-1, audio.shape[-1])
        if audio.ndim == 1:
            audio = audio.reshape(-1, 1)
        if audio.ndim == 2 and int(audio.shape[1]) != self.channels:
            if int(audio.shape[1]) > self.channels:
                audio = audio.mean(axis=1, keepdims=True)
            if self.channels > int(audio.shape[1]):
                audio = np.repeat(audio[:, :1], self.channels, axis=1)
        audio = np.nan_to_num(audio, nan=0.0, posinf=0.0, neginf=0.0)
        gain = float(self.config.moss_output_gain)
        if gain != 1.0:
            audio = audio * gain
        max_abs_before = float(np.max(np.abs(audio))) if audio.size else 0.0
        target_peak = float(self.config.moss_output_target_peak)
        scale = 1.0
        if self.config.moss_output_peak_normalize_enabled and max_abs_before > target_peak > 0:
            scale = target_peak / max_abs_before
            audio = audio * scale
        clipped = np.clip(audio, -1.0, 1.0)
        clip_ratio = float(np.mean(np.abs(clipped) >= 0.999)) if clipped.size else 0.0
        if update_quality:
            self._last_output_quality = {
                "max_abs_before": round(max_abs_before, 6),
                "scale": round(scale, 6),
                "max_abs_after": round(float(np.max(np.abs(clipped))) if clipped.size else 0.0, 6),
                "clip_ratio": round(clip_ratio, 6),
            }
        return clipped.astype(np.float32, copy=False)

    def _ensure_import_path(self) -> None:
        repo_path = self.config.moss_repo_path
        if repo_path:
            resolved = str(Path(repo_path).expanduser().resolve())
            if resolved not in sys.path:
                sys.path.insert(0, resolved)

    def _create_runtime(self, provider: str):
        try:
            from onnx_tts_runtime import OnnxTtsRuntime
        except ModuleNotFoundError as exc:
            missing = exc.name or "unknown"
            if missing != "onnx_tts_runtime":
                raise RuntimeError(
                    f"MOSS-TTS-Nano runtime dependency is missing: {missing}. "
                    "Use an AngeVoice MOSS-enabled image or install the official MOSS runtime dependencies."
                ) from exc
            raise RuntimeError(
                "MOSS-TTS-Nano runtime is not installed. Install the official OpenMOSS package "
                "or set MOSS_TTS_NANO_PATH to a local clone."
            ) from exc

        runtime_kwargs = {
            "model_dir": str(self.config.moss_model_dir) if self.config.moss_model_dir else None,
            "thread_count": self.config.moss_cpu_threads,
            "max_new_frames": self.config.moss_max_new_frames,
            "do_sample": self.config.moss_sample_mode != "greedy",
            "sample_mode": self.config.moss_sample_mode,
            "execution_provider": provider,
        }
        if provider != "cuda" or int(self.config.moss_cuda_memory_limit_mb) <= 0:
            return OnnxTtsRuntime(**runtime_kwargs)

        import ort_cpu_runtime

        original_resolver = ort_cpu_runtime._resolve_ort_providers
        limit_bytes = int(self.config.moss_cuda_memory_limit_mb) * 1024 * 1024

        def _resolve_limited_ort_providers(execution_provider: str):
            resolved = original_resolver(execution_provider)
            if not any(item == "CUDAExecutionProvider" or (isinstance(item, tuple) and item[0] == "CUDAExecutionProvider") for item in resolved):
                return resolved
            logger.info("Applying MOSS CUDA memory limit: %d MB", int(self.config.moss_cuda_memory_limit_mb))
            return [
                (
                    "CUDAExecutionProvider",
                    {
                        "gpu_mem_limit": limit_bytes,
                        "arena_extend_strategy": "kSameAsRequested",
                        "cudnn_conv_use_max_workspace": 0,
                    },
                ),
                "CPUExecutionProvider",
            ]

        with self._provider_patch_lock:
            try:
                ort_cpu_runtime._resolve_ort_providers = _resolve_limited_ort_providers
                return OnnxTtsRuntime(**runtime_kwargs)
            finally:
                ort_cpu_runtime._resolve_ort_providers = original_resolver

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
        import numpy as np

        audio = normalize_audio_array(waveform)
        if audio.size == 0:
            return {"ok": False, "reason": "empty audio"}
        if not np.isfinite(audio).all():
            return {"ok": False, "reason": "audio contains NaN or Inf"}
        max_abs = float(np.max(np.abs(audio)))
        if max_abs < 1e-4:
            return {"ok": False, "reason": "near-silent audio", "max_abs": max_abs}
        clip_ratio = float(np.mean(np.abs(audio) >= 0.999))
        if clip_ratio > float(self.config.moss_max_clip_ratio):
            return {"ok": False, "reason": "audio clipping ratio is too high", "clip_ratio": clip_ratio}
        return {
            "ok": True,
            "sample_rate": sample_rate,
            "channels": int(audio.shape[1]) if audio.ndim == 2 else 1,
            "samples": int(audio.shape[0]),
            "max_abs": round(max_abs, 6),
            "clip_ratio": round(clip_ratio, 6),
        }

    def _validate_request(self, text: str, voice: str, speed: float) -> None:
        if not self._loaded or self._runtime is None:
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
        text = "".join(c if c.isprintable() or c.isspace() else " " for c in str(text or ""))
        text = " ".join(text.split()).strip()
        if self.config.moss_apply_angevoice_rules:
            text = normalize_text_for_tts(text, model="moss")
        return text

    def _segment_text(self, text: str) -> list[str]:
        """Split text into segments for incremental synthesis.

        Uses the same punctuation-aware logic as the Kokoro engine: accumulate
        characters until *segment_length* is reached and a punctuation boundary
        is found, then cut.  A hard-cut at 1.5x length prevents runaway loops
        on punctuation-free text.
        """
        max_len = max(20, int(self.config.segment_length))
        punctuation = "。！？!?；;，,、.：:\n"
        segments: list[str] = []
        current = ""

        for char in text:
            current += char
            if len(current) >= max_len and char in punctuation:
                if current.strip():
                    segments.append(current.strip())
                current = ""
                continue
            if len(current) >= int(max_len * 1.5):
                cut_pos = max(current.rfind(p) for p in punctuation)
                if cut_pos >= max_len // 2:
                    head = current[: cut_pos + 1].strip()
                    tail = current[cut_pos + 1 :].strip()
                    if head:
                        segments.append(head)
                    current = tail
                else:
                    if current.strip():
                        segments.append(current.strip())
                    current = ""

        if current.strip():
            segments.append(current.strip())
        return segments or [text]

    def _temp_output_path(self) -> str:
        temp_dir = Path(tempfile.gettempdir()) / "angevoice_moss"
        temp_dir.mkdir(parents=True, exist_ok=True)
        return str(temp_dir / "last_output.wav")
