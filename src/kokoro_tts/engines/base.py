"""Shared public engine contracts for AngeVoice.

Phase 1 deliberately keeps the mature Kokoro and MOSS implementations intact.
Adapters expose a stable product-level model identity while delegating synthesis
work to the existing runtime implementations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class ProviderStatus:
    """Runtime provider decision exposed in model status responses."""

    requested_provider: str
    actual_provider: str | None = None
    fallback: bool = False
    fallback_reason: str = ""
    assume_requested_if_unknown: bool = True

    def as_dict(self) -> dict[str, Any]:
        actual = self.actual_provider
        if actual is None and self.assume_requested_if_unknown:
            actual = self.requested_provider
        return {
            "requested_provider": self.requested_provider,
            "actual_provider": actual,
            "fallback": self.fallback,
            "fallback_reason": self.fallback_reason,
        }


@dataclass(frozen=True)
class EngineCapabilities:
    """Stable feature declaration consumed by routes and the UI."""

    modes: tuple[str, ...]
    voice_clone_supported: bool
    speed_supported: bool
    text_rules_enabled: bool = True
    requires_prompt_audio: bool = False
    requires_prompt_text: bool = False
    supports_saved_voice_profiles: bool = False
    stream_mode: str = "segmented"
    provider_fallback: bool = False
    sample_rate: int | None = None
    channels: int | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "modes": list(self.modes),
            "voice_clone_supported": self.voice_clone_supported,
            "voice_clone_enabled": self.voice_clone_supported,
            "speed_supported": self.speed_supported,
            "text_rules_enabled": self.text_rules_enabled,
            "requires_prompt_audio": self.requires_prompt_audio,
            "requires_prompt_text": self.requires_prompt_text,
            "supports_saved_voice_profiles": self.supports_saved_voice_profiles,
            "stream_mode": self.stream_mode,
            "provider_fallback": self.provider_fallback,
        }
        if self.sample_rate is not None:
            payload["sample_rate"] = self.sample_rate
        if self.channels is not None:
            payload["channels"] = self.channels
        return payload


@dataclass(frozen=True)
class EngineSpec:
    """One product-level model visible in public model catalogs."""

    id: str
    name: str
    backend: str
    provider: str
    experimental: bool = False


@dataclass(frozen=True)
class ModelResolution:
    """Resolution of user input to a product model and optional runtime hint."""

    original_id: str
    canonical_id: str
    provider_hint: str | None = None
    deprecated_alias: bool = False


@runtime_checkable
class EngineAdapter(Protocol):
    """Minimal adapter surface used by the existing manager and routes."""

    @property
    def is_loaded(self) -> bool: ...

    @property
    def is_healthy(self) -> bool: ...

    def load(self): ...

    def unload(self, *args, **kwargs) -> None: ...

    def capabilities(self) -> EngineCapabilities: ...

    def metadata(self) -> dict[str, Any]: ...

    def synthesize(self, text: str, voice: str = "", speed: float = 1.0, **kwargs) -> bytes: ...

    def synthesize_array(self, text: str, voice: str = "", speed: float = 1.0, **kwargs): ...

    def synthesize_stream(self, text: str, voice: str = "", speed: float = 1.0, fmt: str = "pcm_s16le", **kwargs): ...
