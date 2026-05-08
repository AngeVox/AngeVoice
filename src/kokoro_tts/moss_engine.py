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
import sys
import tempfile
import time
import threading
from collections import OrderedDict
from contextlib import suppress
from pathlib import Path
from typing import Optional

from .audio import encode_audio_segment, normalize_audio_array, write_wav_bytes
from .config import TTSConfig
from .engine import normalize_text_for_tts

logger = logging.getLogger(__name__)

# Silence between concatenated segments (seconds)
_SEGMENT_SILENCE_SECONDS = 0.08


class MossNanoEngine:
    """Adapter around OpenMOSS' official ONNX runtime."""

    SUPPORTED_STREAM_FORMATS = {"pcm_s16le", "wav"}

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

    @property
    def is_loaded(self) -> bool:
        return self._loaded

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
            "speed_supported": False,
            "text_rules_enabled": bool(self.config.moss_apply_angevoice_rules),
            "experimental": self.execution_provider == "cuda",
            "error": self._load_error,
            "self_test": self._self_test,
            "last_output_quality": self._last_output_quality,
            "prompt_audio_max_seconds": self.config.moss_prompt_audio_max_seconds,
            "output_target_peak": self.config.moss_output_target_peak,
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

    def unload(self) -> None:
        with self._runtime_lock:
            self._runtime = None
            self._loaded = False
            with self._prompt_cache_lock:
                self._prompt_audio_code_cache.clear()
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
            raise RuntimeError(
                f"MOSS inference timed out ({timeout}s). "
                "CUDA inference may be stuck. Try switching to CPU or restarting."
            )

    def synthesize_stream(self, text, voice="", speed=1.0, fmt="pcm_s16le", prompt_audio_path: str | None = None):
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

        total_done = 0

        try:
            with self._runtime_lock:
                for i, waveform in enumerate(self._iter_waveforms(segments=segments, voice=voice, prompt_audio_path=prompt_audio)):
                    audio_bytes = encode_audio_segment(waveform, fmt, self.sample_rate)
                    yield {
                        "type": "audio",
                        "index": i,
                        "data": base64.b64encode(audio_bytes).decode("ascii"),
                        "format": fmt,
                        "sample_rate": self.sample_rate,
                        "channels": self.channels,
                    }
                    total_done += 1
        except Exception as exc:
            logger.warning("MOSS stream failed: %s", exc)
            yield {"type": "segment_error", "index": total_done, "message": str(exc), "model": self.engine_id}

        yield {"type": "done", "total_segments": total_done}

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

    def _iter_runtime_chunks(self, text: str, *, voice: str = "", prompt_audio_codes: list[list[int]]):
        import numpy as np

        prepared_texts = self._runtime.prepare_synthesis_text(
            text=text,
            voice=voice or self.default_voice,
            enable_wetext=bool(self.config.moss_enable_wetext_processing),
            enable_normalize_tts_text=bool(self.config.moss_enable_normalize_tts_text),
        )
        prepared_text = str(prepared_texts["text"])
        text_chunks = self._runtime.split_voice_clone_text(
            prepared_text,
            max_tokens=int(self.config.moss_voice_clone_max_text_tokens),
        )
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

    def _configure_runtime_generation(self) -> None:
        generation = self._runtime.manifest["generation_defaults"]
        generation["max_new_frames"] = int(self.config.moss_max_new_frames)
        generation["sample_mode"] = self.config.moss_sample_mode
        generation["do_sample"] = self.config.moss_sample_mode != "greedy"

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

    def _postprocess_waveform(self, waveform):
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

        return OnnxTtsRuntime(
            model_dir=str(self.config.moss_model_dir) if self.config.moss_model_dir else None,
            thread_count=self.config.moss_cpu_threads,
            max_new_frames=self.config.moss_max_new_frames,
            do_sample=self.config.moss_sample_mode != "greedy",
            sample_mode=self.config.moss_sample_mode,
            execution_provider=provider,
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
