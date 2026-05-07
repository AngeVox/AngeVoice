"""Pydantic request/response models for AngeVoice HTTP APIs."""

from pydantic import BaseModel, ConfigDict, Field


class TTSRequest(BaseModel):
    """OpenAI-compatible speech request.

    ``input`` is the OpenAI-compatible field name. ``text`` remains accepted as
    an alias for older local clients.
    """

    model: str = Field(default="kokoro", description="Model id, for example kokoro or moss-nano-cpu")
    input: str = Field(..., description="Text to synthesize", alias="text")
    voice: str = Field(default="zm_010", description="Voice name")
    speed: float = Field(default=1.0, ge=0.5, le=2.0, description="Speed")
    response_format: str = Field(default="wav", description="wav, pcm, or mp3 when enabled")

    model_config = ConfigDict(populate_by_name=True, extra="ignore")
