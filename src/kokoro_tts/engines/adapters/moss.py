"""Product-level MOSS adapter preserving the current MOSS runtime."""

from __future__ import annotations

from typing import Any

from ...config import TTSConfig
from ...moss_engine import MossNanoEngine
from ..base import EngineCapabilities, ProviderStatus


class MossAdapter:
    """Expose one public ``moss`` model while delegating to ``MossNanoEngine``.

    CPU/CUDA are implementation providers rather than separate user-facing
    models. The underlying MOSS engine already owns CUDA self-test and fallback
    behaviour; this adapter only exposes that result consistently.
    """

    public_id = "moss"
    public_name = "MOSS-TTS-Nano"
    backend = "moss-tts-nano-onnx"

    def __init__(self, cfg: TTSConfig, *, requested_provider: str | None = None):
        provider = str(requested_provider or cfg.moss_execution_provider or "cpu").strip().lower()
        if provider == "cuda" and not bool(getattr(cfg, "moss_cuda_enabled", True)):
            provider = "cpu"
        self._cfg = cfg
        self._requested_provider = "cuda" if provider == "cuda" else "cpu"
        self._engine = MossNanoEngine(cfg, execution_provider=self._requested_provider, engine_id=self.public_id)

    @property
    def requested_provider(self) -> str:
        return self._requested_provider

    @property
    def is_loaded(self) -> bool:
        return bool(self._engine.is_loaded)

    @property
    def is_healthy(self) -> bool:
        return bool(getattr(self._engine, "is_healthy", True))

    def load(self):
        self._engine.load()
        return self

    def unload(self, *args, **kwargs) -> None:
        self._engine.unload(*args, **kwargs)

    def capabilities(self) -> EngineCapabilities:
        text_rules_mode = str(getattr(self._cfg, "moss_apply_angevoice_rules", "auto")).strip().lower()
        return EngineCapabilities(
            modes=("preset_voice", "voice_clone"),
            voice_clone_supported=True,
            speed_supported=False,
            text_rules_enabled=text_rules_mode != "false",
            requires_prompt_audio=False,
            requires_prompt_text=False,
            supports_saved_voice_profiles=False,
            stream_mode="native",
            provider_fallback=True,
            sample_rate=48000,
            channels=2,
        )

    def _provider_status(self, metadata: dict[str, Any]) -> ProviderStatus:
        actual = str(metadata.get("actual_provider") or self._requested_provider).strip().lower()
        fallback = actual != self._requested_provider
        reason = ""
        if fallback:
            self_test = metadata.get("self_test")
            if isinstance(self_test, dict):
                reason = str(self_test.get("reason") or "")
            reason = reason or f"{self._requested_provider} unavailable; using {actual}"
        return ProviderStatus(self._requested_provider, actual, fallback, reason)

    def metadata(self) -> dict[str, Any]:
        value = self._engine.metadata() if callable(getattr(self._engine, "metadata", None)) else {}
        metadata = dict(value) if isinstance(value, dict) else {}
        metadata.update(self.capabilities().as_dict())
        metadata.update(self._provider_status(metadata).as_dict())
        metadata.update({"id": self.public_id, "name": self.public_name, "backend": self.backend})
        return metadata

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(f"private engine attribute is not exposed: {name}")
        return getattr(self._engine, name)
