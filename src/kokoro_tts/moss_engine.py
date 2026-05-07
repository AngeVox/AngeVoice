"""MOSS-TTS-Nano adapter for AngeVoice.

The inference runtime itself stays in the official OpenMOSS package/repository.
This module only adapts that runtime to AngeVoice's engine interface.
"""

from __future__ import annotations

import base64
import concurrent.futures
import gc
import logging
import sys
import tempfile
import time
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
        self._runtime = None
        self._loaded = False
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
        import numpy as np

        self._validate_request(text=text, voice=voice, speed=speed)
        prepared_text = self._clean_text(text)
        segments = self._segment_text(prepared_text)
        prompt_audio = prompt_audio_path or (str(self.config.moss_prompt_audio_path) if self.config.moss_prompt_audio_path else None)
        timeout = self.config.request_timeout_seconds

        logger.info("MOSS synthesize: segments=%d, voice=%s", len(segments), voice or self.default_voice)

        all_waveforms = []

        def _run():
            for i, seg in enumerate(segments):
                if not seg.strip():
                    continue
                t0 = time.monotonic()
                result = self._runtime.synthesize(
                    text=seg,
                    voice=voice or self.default_voice,
                    prompt_audio_path=prompt_audio,
                    output_audio_path=self._temp_output_path(),
                    sample_mode=self.config.moss_sample_mode,
                    do_sample=self.config.moss_sample_mode != "greedy",
                    streaming=bool(self.config.moss_realtime_streaming_decode),
                    max_new_frames=self.config.moss_max_new_frames,
                    voice_clone_max_text_tokens=self.config.moss_voice_clone_max_text_tokens,
                    enable_wetext=bool(self.config.moss_enable_wetext_processing),
                    enable_normalize_tts_text=bool(self.config.moss_enable_normalize_tts_text),
                )
                waveform = normalize_audio_array(result["waveform"])
                all_waveforms.append(waveform)
                elapsed = time.monotonic() - t0
                logger.info("MOSS segment %d/%d done (%.1fs, %d samples)", i + 1, len(segments), elapsed, waveform.shape[0])

            if not all_waveforms:
                raise RuntimeError("MOSS: all segments produced empty audio")

            # Concatenate with inter-segment silence
            sr = self.sample_rate
            silence = np.zeros((int(sr * _SEGMENT_SILENCE_SECONDS), all_waveforms[0].shape[-1]), dtype=np.float32) if all_waveforms[0].ndim == 2 else np.zeros(int(sr * _SEGMENT_SILENCE_SECONDS), dtype=np.float32)
            parts = []
            for idx, wf in enumerate(all_waveforms):
                parts.append(wf)
                if idx < len(all_waveforms) - 1:
                    parts.append(silence)
            return np.concatenate(parts)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_run)
            try:
                return future.result(timeout=timeout)
            except concurrent.futures.TimeoutError:
                future.cancel()
                raise RuntimeError(
                    f"MOSS inference timed out ({timeout}s). "
                    "CUDA inference may be stuck. Try switching to CPU or restarting."
                )

    def synthesize_stream(self, text, voice="", speed=1.0, fmt="pcm_s16le"):
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

        yield {
            "type": "started",
            "segments": len(segments),
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "format": fmt,
            "dtype": "s16le" if fmt == "pcm_s16le" else "wav",
            "model": self.engine_id,
        }

        prompt_audio = str(self.config.moss_prompt_audio_path) if self.config.moss_prompt_audio_path else None
        total_done = 0

        for i, seg in enumerate(segments):
            if not seg.strip():
                continue
            try:
                t0 = time.monotonic()
                result = self._runtime.synthesize(
                    text=seg,
                    voice=voice or self.default_voice,
                    prompt_audio_path=prompt_audio,
                    output_audio_path=self._temp_output_path(),
                    sample_mode=self.config.moss_sample_mode,
                    do_sample=self.config.moss_sample_mode != "greedy",
                    streaming=bool(self.config.moss_realtime_streaming_decode),
                    max_new_frames=self.config.moss_max_new_frames,
                    voice_clone_max_text_tokens=self.config.moss_voice_clone_max_text_tokens,
                    enable_wetext=bool(self.config.moss_enable_wetext_processing),
                    enable_normalize_tts_text=bool(self.config.moss_enable_normalize_tts_text),
                )
                waveform = normalize_audio_array(result["waveform"])
                audio_bytes = encode_audio_segment(waveform, fmt, self.sample_rate)
                elapsed = time.monotonic() - t0
                logger.info("MOSS stream segment %d/%d (%.1fs)", i + 1, len(segments), elapsed)
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
                logger.warning("MOSS stream segment %d failed: %s", i + 1, exc)
                yield {"type": "segment_error", "index": i, "message": str(exc), "model": self.engine_id}

        yield {"type": "done", "total_segments": total_done}

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
