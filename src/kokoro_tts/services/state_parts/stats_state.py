"""Statistics and WebSocket connection state."""

from __future__ import annotations


class StatsStateMixin:
    def inc_stat(self, name: str, delta=1) -> None:
        with self.stats_lock:
            self.stats[name] = self.stats.get(name, 0) + delta

    def snapshot_stats(self) -> dict:
        with self.stats_lock:
            snapshot = dict(self.stats)
        snapshot["ws_connections_active"] = self._websocket_connections
        return snapshot

    async def try_acquire_websocket_connection(self) -> bool:
        """在接受握手前预留一个 WebSocket 会话槽位。"""
        limit = max(0, int(getattr(self.cfg, "websocket_max_connections", 0) or 0))
        async with self._websocket_connection_lock:
            if limit and self._websocket_connections >= limit:
                self.inc_stat("ws_connections_rejected_total")
                return False
            self._websocket_connections += 1
            with self.stats_lock:
                self.stats["ws_connections_peak"] = max(self.stats.get("ws_connections_peak", 0), self._websocket_connections)
            return True

    async def release_websocket_connection(self) -> None:
        async with self._websocket_connection_lock:
            self._websocket_connections = max(0, self._websocket_connections - 1)

    @property
    def active_websocket_connections(self) -> int:
        return self._websocket_connections

