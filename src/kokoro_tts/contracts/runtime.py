"""Runtime resource and provider reporting contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RuntimeResourceStatus:
    rss_bytes: int | None
    cache_items: int
    cache_bytes: int
    cache_hits: int
    cache_misses: int
    cache_skips: int
    models: list[dict[str, Any]] = field(default_factory=list)
    current_model: str = ""
    active_requests: int = 0
    sampled_at: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "rss_bytes": self.rss_bytes,
            "cache_items": self.cache_items,
            "cache_bytes": self.cache_bytes,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "cache_skips": self.cache_skips,
            "models": self.models,
            "current_model": self.current_model,
            "active_requests": self.active_requests,
            "sampled_at": self.sampled_at,
        }
