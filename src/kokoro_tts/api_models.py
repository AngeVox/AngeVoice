"""Pydantic request/response models for AngeVoice HTTP APIs."""

from pydantic import BaseModel, ConfigDict, Field


class TTSRequest(BaseModel):
    """OpenAI-compatible speech request.

    ``input`` is the OpenAI-compatible field name. ``text`` remains accepted as
    an alias for older local clients.
    """

    model: str = Field(default="kokoro", description="Model id, for example kokoro or moss-nano-cpu")
    input: str = Field(..., min_length=1, description="Text to synthesize", alias="text")
    voice: str = Field(default="zm_010", description="Voice name")
    speed: float = Field(default=1.0, ge=0.5, le=2.0, description="Speed")
    response_format: str = Field(default="wav", description="wav, pcm, or mp3 when enabled")
    response_encoding: str = Field(
        default="binary",
        description="binary for audio bytes, or base64/json for a JSON payload containing a data URL",
    )
    emotion: str | None = Field(
        default=None,
        description="Reserved for future/provider-specific emotion control. Unsupported engines ignore it.",
    )
    emotion_strength: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Reserved normalized emotion strength for future/provider-specific engines.",
    )
    style_prompt: str | None = Field(
        default=None,
        description="Reserved style instruction for engines that support style/emotion prompts.",
    )

    model_config = ConfigDict(populate_by_name=True, extra="ignore")
