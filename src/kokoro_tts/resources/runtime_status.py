"""Runtime resource snapshots and controlled release operations."""

from __future__ import annotations

import gc
import os
import resource
import time
from typing import TYPE_CHECKING

from ..contracts import RuntimeResourceStatus

if TYPE_CHECKING:
    from ..service_state import ServiceState


class RuntimeResourceService:
    def __init__(self, state: "ServiceState"):
        self.state = state

    @staticmethod
    def rss_bytes() -> int | None:
        try:
            with open("/proc/self/status", "r", encoding="utf-8") as handle:
                for line in handle:
                    if line.startswith("VmRSS:"):
                        return int(line.split()[1]) * 1024
        except (OSError, ValueError, IndexError):
            pass
        try:
            value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
            return value * (1 if os.uname().sysname == "Darwin" else 1024)
        except Exception:
            return None

    def snapshot(self) -> dict:
        stats = self.state.snapshot_stats()
        active = [
            value for value in self.state.active_requests.values()
            if value.get("status") in {"queued", "running", "cancelling"}
        ]
        return RuntimeResourceStatus(
            rss_bytes=self.rss_bytes(),
            cache_items=self.state.cache_size(),
            cache_bytes=self.state.cache_bytes(),
            cache_hits=int(stats.get("cache_hits", 0)),
            cache_misses=int(stats.get("cache_misses", 0)),
            cache_skips=int(stats.get("cache_skips", 0)),
            models=self.state.model_manager.list_models(),
            current_model=self.state.model_manager.current_model_id,
            active_requests=len(active),
            sampled_at=time.time(),
        ).as_dict()

    def release(self, *, clear_cache: bool = True, unload_models: bool = False, include_current: bool = True) -> dict:
        before = self.snapshot()
        cleared = self.state.cache_clear() if clear_cache else 0
        unloaded = self.state.model_manager.unload_inactive(force=False, include_current=include_current) if unload_models else []
        collected = gc.collect()
        after = self.snapshot()
        return {
            "ok": True,
            "cleared_cache_items": cleared,
            "unloaded_models": unloaded,
            "gc_collected": collected,
            "before": before,
            "after": after,
        }
