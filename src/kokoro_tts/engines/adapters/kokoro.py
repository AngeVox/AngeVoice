"""Product-level Kokoro adapter preserving the existing engine runtime."""

from __future__ import annotations

from typing import Any

from ...config import TTSConfig
from ...engine import TTSEngine
from ..base import EngineCapabilities


class KokoroAdapter:
    """Thin adapter around :class:`TTSEngine`.

    The adapter intentionally delegates synthesis and lifecycle behaviour without
    rewriting the established Kokoro implementation in Phase 1.
    """

    public_id = "kokoro"
    public_name = "Kokoro v1.1 Chinese"
    backend = "kokoro"

    def __init__(self, cfg: TTSConfig, engine: TTSEngine | None = None):
        self._engine = engine or TTSEngine(cfg)
        self._cfg = cfg

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
        self._engine.unload()

    def capabilities(self) -> EngineCapabilities:
        return EngineCapabilities(
            modes=("preset_voice",),
            voice_clone_supported=False,
            speed_supported=True,
            text_rules_enabled=True,
            stream_mode="segmented",
            sample_rate=int(getattr(self._cfg, "sample_rate", 24000)),
            channels=1,
        )

    def metadata(self) -> dict[str, Any]:
        value = self._engine.metadata() if callable(getattr(self._engine, "metadata", None)) else {}
        metadata = dict(value) if isinstance(value, dict) else {}
        metadata.update(self.capabilities().as_dict())
        metadata.update({"id": self.public_id, "name": self.public_name, "backend": self.backend})
        return metadata

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(f"private engine attribute is not exposed: {name}")
        return getattr(self._engine, name)
