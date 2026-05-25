"""ZipVoice adapter with optional killable worker isolation and safe CPU fallback."""

from __future__ import annotations

import base64
import logging
import threading
from io import BytesIO
from typing import Any, Callable

from ..audio import encode_audio_segment
from ..engines.base import EngineCapabilities, ProviderStatus
from ..text_segmenter import segment_text_natural
from ..workers import EngineProcessClient
from .assets import ZipVoiceAssetManager
from .profiles import ZipVoiceProfileStore

logger = logging.getLogger(__name__)


class ZipVoiceEngine:
    public_id = "zipvoice"

    def __init__(self, cfg, *, profile_store=None, requested_provider: str | None = None, process_isolation: bool | None = None):
        self.cfg = cfg
        self.requested_provider = str(requested_provider or getattr(cfg, "zipvoice_execution_provider", "cpu") or "cpu").strip().lower()
        configured = bool(getattr(cfg, "zipvoice_process_isolation_enabled", False))
        self._process_isolated = configured if process_isolation is None else bool(process_isolation)
        self.profiles = profile_store or ZipVoiceProfileStore(cfg)
        self.assets = ZipVoiceAssetManager(cfg)
        self._worker = EngineProcessClient(config=cfg, engine_id="zipvoice", requested_provider=self.requested_provider, logger=logger) if self._process_isolated else None
        self._cpu_runtime = None
        self._cuda_runtime = None
        self.runtime = None
        if not self._process_isolated:
            self._init_local_runtime()
        self._unhealthy = False
        self._actual_provider: str | None = None
        self._fallback = False
        self._fallback_reason = ""
        self._state_lock = threading.RLock()

    def _init_local_runtime(self) -> None:
        from .runtime_cpu_onnx import ZipVoiceOnnxCpuRuntime
        self._cpu_runtime = ZipVoiceOnnxCpuRuntime(self.cfg)
        if self.requested_provider == "cuda":
            from .runtime_cuda_torch import ZipVoiceTorchCudaRuntime
            self._cuda_runtime = ZipVoiceTorchCudaRuntime(self.cfg)
        self.runtime = self._cuda_runtime or self._cpu_runtime
        self.assets = self.runtime.assets

    @property
    def public_name(self) -> str:
        return "ZipVoice"

    @property
    def backend(self) -> str:
        return "zipvoice-distill-pytorch-cuda" if self.requested_provider == "cuda" else "zipvoice-distill-onnx-int8"

    @property
    def is_loaded(self) -> bool:
        if self._worker is not None:
            return self._worker.is_loaded
        return bool(self.runtime and self.runtime.loaded)

    @property
    def is_healthy(self) -> bool:
        if self._worker is not None:
            return bool(self._worker.is_healthy and not self._unhealthy)
        return not self._unhealthy

    @property
    def sample_rate(self) -> int:
        if self.runtime is not None:
            return int(self.runtime.sample_rate or 24000)
        return 24000

    @property
    def channels(self) -> int:
        return 1

    @property
    def default_voice(self) -> str:
        profiles = self.get_voices()
        return profiles[0] if profiles else ""

    def get_voices(self) -> list[str]:
        return [item["voice_id"] for item in self.profiles.list()]

    def load(self):
        with self._state_lock:
            if self._worker is not None:
                try:
                    metadata = self._worker.load(timeout=float(getattr(self.cfg, "model_switch_timeout_seconds", 300.0)))
                    self._actual_provider = str(metadata.get("actual_provider") or "") or None
                    self._fallback = bool(metadata.get("provider_fallback", False))
                    self._fallback_reason = str(metadata.get("fallback_reason") or "")
                    self._unhealthy = False
                except Exception:
                    self._unhealthy = True
                    self._worker.close(kill=True)
                    raise
                return self
            try:
                if self.requested_provider == "cuda" and self._cuda_runtime is not None:
                    try:
                        self._cuda_runtime.load()
                        self.runtime = self._cuda_runtime
                        self.assets = self.runtime.assets
                        self._actual_provider = "cuda_pytorch"
                        self._fallback = False
                        self._fallback_reason = ""
                    except Exception as exc:
                        if not bool(getattr(self.cfg, "zipvoice_auto_fallback_cpu", True)):
                            raise
                        try:
                            self._cuda_runtime.unload()
                        except Exception:
                            logger.debug("Failed to release partial ZipVoice CUDA runtime before fallback", exc_info=True)
                        logger.warning("ZipVoice CUDA unavailable; falling back to ONNX INT8 CPU: %s", exc)
                        self._cpu_runtime.load()
                        self.runtime = self._cpu_runtime
                        self.assets = self.runtime.assets
                        self._actual_provider = "cpu_onnx_int8"
                        self._fallback = True
                        self._fallback_reason = f"CUDA runtime unavailable: {exc}"
                else:
                    self._cpu_runtime.load()
                    self.runtime = self._cpu_runtime
                    self.assets = self.runtime.assets
                    self._actual_provider = "cpu_onnx_int8"
                    self._fallback = False
                    self._fallback_reason = ""
                self._unhealthy = False
            except Exception:
                self._unhealthy = True
                raise
            return self

    def unload(self, *args, **kwargs) -> None:
        with self._state_lock:
            if self._worker is not None:
                self._worker.close(kill=bool(kwargs.get("force", False)))
                return
            if self._cuda_runtime is not None:
                self._cuda_runtime.unload()
            if self._cpu_runtime is not None:
                self._cpu_runtime.unload()

    def capabilities(self) -> EngineCapabilities:
        return EngineCapabilities(
            modes=("voice_clone", "saved_voice_profile"), voice_clone_supported=True,
            speed_supported=True, text_rules_enabled=True, requires_prompt_audio=True,
            requires_prompt_text=True, supports_saved_voice_profiles=True,
            stream_mode="segmented", provider_fallback=self.requested_provider == "cuda",
            sample_rate=24000, channels=1,
        )

    def metadata(self) -> dict[str, Any]:
        with self._state_lock:
            assets = self.assets.status()
            worker_meta = self._worker.last_metadata if self._worker is not None else {}
            result = {
                "id": self.public_id, "name": self.public_name, "backend": self.backend,
                "loaded": self.is_loaded, "healthy": self.is_healthy, "wakeable": True,
                "default_voice": self.default_voice, "voices": self.get_voices(),
                "saved_voice_profiles": len(self.get_voices()), "assets_ready": assets["ready"],
                "assets_status_file": assets["status_file"],
                "process_isolated": self._process_isolated,
                "process_alive": bool(self._worker and self._worker.alive),
                "worker_pid": self._worker.pid if self._worker else None,
                "worker_healthy": self._worker.is_healthy if self._worker else None,
                "worker_last_exit_reason": self._worker.last_exit_reason if self._worker else "",
                "release_guarantee": "worker_exit" if self._process_isolated else "in_process_best_effort",
            }
            result.update(self.capabilities().as_dict())
            actual = str(worker_meta.get("actual_provider") or self._actual_provider or "") or ("cpu_onnx_int8" if self.requested_provider == "cpu" else None)
            fallback = bool(worker_meta.get("provider_fallback", self._fallback))
            reason = str(worker_meta.get("fallback_reason") or self._fallback_reason or "")
            result.update(ProviderStatus(self.requested_provider, actual, fallback, reason, assume_requested_if_unknown=self.is_loaded).as_dict())
            if self.runtime is not None:
                result.update(self.runtime.last_metrics)
            return result

    def _timeout(self) -> float:
        return float(getattr(self.cfg, "request_timeout_seconds", 300.0))

    def synthesize(self, text: str, voice: str = "", speed: float = 1.0, *, prompt_audio_path: str | None = None, prompt_text: str = "", zipvoice_num_steps: int | None = None, zipvoice_remove_long_sil: bool | None = None) -> bytes:
        kwargs = {
            "text": text, "voice": voice, "speed": speed,
            "prompt_audio_path": prompt_audio_path, "prompt_text": prompt_text,
            "zipvoice_num_steps": zipvoice_num_steps, "zipvoice_remove_long_sil": zipvoice_remove_long_sil,
        }
        with self._state_lock:
            if not self.is_loaded:
                self.load()
            if self._worker is not None:
                return self._worker.request("synthesize", kwargs, timeout=self._timeout())
            runtime_kwargs = {
                "text": text, "prompt_audio_path": str(prompt_audio_path or ""), "prompt_text": prompt_text,
                "speed": speed, "num_steps": zipvoice_num_steps, "remove_long_sil": zipvoice_remove_long_sil,
            }
            try:
                return self.runtime.synthesize(**runtime_kwargs)
            except RuntimeError as exc:
                if not (self.requested_provider == "cuda" and self.runtime is self._cuda_runtime and bool(getattr(self.cfg, "zipvoice_auto_fallback_cpu", True))):
                    raise
                logger.warning("ZipVoice CUDA synthesis failed; retrying with ONNX INT8 CPU: %s", exc)
                try:
                    self._cuda_runtime.unload()
                except Exception:
                    logger.debug("Failed to release ZipVoice CUDA runtime before inference fallback", exc_info=True)
                self._cpu_runtime.load()
                self.runtime = self._cpu_runtime
                self.assets = self.runtime.assets
                self._actual_provider = "cpu_onnx_int8"
                self._fallback = True
                self._fallback_reason = f"CUDA synthesis failed: {exc}"
                return self.runtime.synthesize(**runtime_kwargs)

    def synthesize_array(self, text: str, voice: str = "", speed: float = 1.0, **kwargs):
        if self._worker is not None:
            if not self.is_loaded:
                self.load()
            payload = {"text": text, "voice": voice, "speed": speed, **kwargs}
            return self._worker.request("synthesize_array", payload, timeout=self._timeout())
        import soundfile as sf
        data, _sample_rate = sf.read(BytesIO(self.synthesize(text, voice, speed, **kwargs)), dtype="float32", always_2d=False)
        return data

    def synthesize_stream(
        self, text: str, voice: str = "", speed: float = 1.0, fmt: str = "pcm_s16le", *,
        prompt_audio_path: str | None = None, prompt_text: str = "", cancel_check: Callable[[], bool] | None = None,
        zipvoice_num_steps: int | None = None, zipvoice_remove_long_sil: bool | None = None,
    ):
        if self._worker is not None:
            if not self.is_loaded:
                self.load()
            yield from self._worker.stream({
                "text": text, "voice": voice, "speed": speed, "fmt": fmt,
                "prompt_audio_path": prompt_audio_path, "prompt_text": prompt_text,
                "zipvoice_num_steps": zipvoice_num_steps, "zipvoice_remove_long_sil": zipvoice_remove_long_sil,
            }, timeout=self._timeout(), cancel_check=cancel_check)
            return
        if fmt not in {"pcm_s16le", "wav"}:
            yield {"type": "error", "message": f"不支持的流式音频格式：{fmt}"}; return
        if not str(text or "").strip():
            yield {"type": "error", "message": "文本不能为空"}; return
        if not prompt_audio_path or not str(prompt_text or "").strip():
            yield {"type": "error", "message": "ZipVoice 流式生成需要参考音频与参考文本，或选择已保存音色"}; return
        segments = segment_text_natural(str(text), max_text_length=int(getattr(self.cfg, "max_text_length", 5000) or 5000), segment_length=int(getattr(self.cfg, "segment_length", 120) or 120), flush_sentence_boundaries=True)
        if not segments:
            yield {"type": "error", "message": "文本清理后为空"}; return
        yield {"type": "started", "segments": len(segments), "sample_rate": self.sample_rate, "channels": 1, "format": fmt, "dtype": "s16le" if fmt == "pcm_s16le" else "wav", "stream_mode": "segmented", "model": self.public_id, "voice_clone": True, "recommended_prebuffer_seconds": float(getattr(self.cfg, "stream_prebuffer_seconds", 0.25))}
        audio_index = 0
        for segment_index, segment in enumerate(segments):
            if cancel_check is not None and bool(cancel_check()):
                break
            try:
                wav_bytes = self.synthesize(segment, voice, speed, prompt_audio_path=prompt_audio_path, prompt_text=prompt_text, zipvoice_num_steps=zipvoice_num_steps, zipvoice_remove_long_sil=zipvoice_remove_long_sil)
                import soundfile as sf
                audio, sample_rate = sf.read(BytesIO(wav_bytes), dtype="float32", always_2d=False)
                payload = encode_audio_segment(audio, fmt, int(sample_rate))
                yield {"type": "audio", "index": audio_index, "segment_index": segment_index, "data": base64.b64encode(payload).decode("ascii"), "format": fmt, "sample_rate": int(sample_rate), "channels": 1}
                audio_index += 1
            except Exception as exc:
                yield {"type": "segment_error", "index": segment_index, "message": str(exc), "model": self.public_id}; break
        yield {"type": "done", "total_segments": len(segments), "total_audio_chunks": audio_index, "stream_mode": "segmented"}
