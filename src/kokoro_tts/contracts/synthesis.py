"""Model-neutral synthesis request, parameter, result and voice-condition contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class VoiceConditionKind(str, Enum):
    """How an engine receives voice identity or reference conditioning."""

    PRESET = "preset"
    UPLOADED_REFERENCE = "uploaded_reference"
    SAVED_PROFILE = "saved_profile"


@dataclass(frozen=True)
class VoiceCondition:
    """Resolved voice input shared by every adapter.

    Routes do not need to know whether a selected voice is a preset, a saved
    reference profile, or a browser/uploaded recording.  New engines register
    capabilities and a profile store rather than adding route branches.
    """

    kind: VoiceConditionKind = VoiceConditionKind.PRESET
    engine_id: str = ""
    voice_id: str = ""
    prompt_audio_path: str | None = None
    prompt_audio_id: str = ""
    prompt_text: str = ""
    revision: str = ""
    language: str = ""
    speaker_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_reference_conditioned(self) -> bool:
        return bool(self.prompt_audio_path)

    @property
    def cache_audio_id(self) -> str:
        return str(self.prompt_audio_id or "")

    def as_dict(self, *, include_path: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": self.kind.value,
            "engine_id": self.engine_id,
            "voice_id": self.voice_id,
            "prompt_audio_id": self.prompt_audio_id,
            "prompt_text_present": bool(self.prompt_text),
            "revision": self.revision,
            "language": self.language,
            "speaker_id": self.speaker_id,
            "metadata": dict(self.metadata),
            "reference_conditioned": self.is_reference_conditioned,
        }
        if include_path:
            payload["prompt_audio_path"] = self.prompt_audio_path
        return payload


@dataclass(frozen=True)
class GenerationParameters:
    """Engine-validated generation controls carried independently from routes."""

    values: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return dict(self.values)


@dataclass(frozen=True)
class SynthesisRequest:
    """Validated internal request used for all non-streaming synthesis."""

    text: str
    model_id: str
    voice: str
    speed: float
    response_format: str = "wav"
    response_encoding: str = "binary"
    condition: VoiceCondition = field(default_factory=VoiceCondition)
    generation: GenerationParameters = field(default_factory=GenerationParameters)
    request_id: str = ""

    @property
    def engine_params(self) -> dict[str, Any]:
        """Legacy service-facing alias while adapters migrate to ``generation``."""
        return self.generation.as_dict()

    def cache_controls(self) -> dict[str, Any]:
        return self.generation.as_dict()


@dataclass(frozen=True)
class SynthesisResult:
    """Model-neutral synthesized audio result envelope for service adapters."""

    audio_bytes: bytes
    media_type: str
    model_id: str
    request_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_response_tuple(self) -> tuple[bytes, str]:
        return self.audio_bytes, self.media_type
