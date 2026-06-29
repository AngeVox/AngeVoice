"""Request id, request registry, and cancellation state."""

from __future__ import annotations

import re
import time
import uuid

_CLIENT_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{5,63}$")
_ACTIVE_REQUEST_STATUSES = {"queued", "running", "streaming", "loading", "processing", "cancelling"}


def normalize_client_request_id(value) -> str | None:
    """Return a safe caller-supplied request id, or None when invalid."""

    text = str(value or "").strip()
    return text if _CLIENT_REQUEST_ID_RE.fullmatch(text) else None


class RequestRegistryMixin:
    def new_request_id(self) -> str:
        return uuid.uuid4().hex[:12]

    def request_id_from_client(self, value) -> str:
        return normalize_client_request_id(value) or self.new_request_id()

    def mark_request(self, request_id: str, status: str, **extra) -> None:
        if not self.cfg.queue_status_enabled:
            return
        with self.request_lock:
            item = self.active_requests.setdefault(
                request_id,
                {"id": request_id, "created_at": time.time(), "status": status},
            )
            item.update({"status": status, "updated_at": time.time(), **extra})

    def request_snapshot(self, *, limit: int | None = None, recent_first: bool = True) -> list[dict]:
        """返回稳定请求快照，不暴露实时共享映射。"""
        with self.request_lock:
            values = [dict(item) for item in self.active_requests.values()]
        values.sort(key=lambda item: float(item.get("updated_at", 0) or 0), reverse=recent_first)
        return values[:limit] if limit is not None else values

    def request_info(self, request_id: str) -> dict | None:
        with self.request_lock:
            item = self.active_requests.get(request_id)
            return dict(item) if item is not None else None

    def request_is_active(self, request_id: str) -> bool:
        item = self.request_info(request_id)
        return bool(item and str(item.get("status", "")).lower() in _ACTIVE_REQUEST_STATUSES)

    def _prune_request_history(self, *, maximum: int = 100, remove_count: int = 20) -> None:
        """清理已完成的历史记录条目，不移除正在运行的请求。"""
        terminal = {"done", "error", "timeout", "cancelled"}
        with self.request_lock:
            if not self.cfg.queue_status_enabled or len(self.active_requests) <= maximum:
                return
            candidates = [
                (key, float(item.get("updated_at", 0) or 0))
                for key, item in self.active_requests.items()
                if item.get("status") in terminal
            ]
            for key, _updated_at in sorted(candidates, key=lambda pair: pair[1])[:remove_count]:
                self.active_requests.pop(key, None)

    def finish_request(self, request_id: str, status: str, **extra) -> None:
        self.mark_request(request_id, status, **extra)
        if status in {"done", "error", "timeout", "cancelled"}:
            with self.request_lock:
                self.cancelled_requests.discard(request_id)
        self._prune_request_history()

    def is_cancelled(self, request_id: str) -> bool:
        with self.request_lock:
            return request_id in self.cancelled_requests

    def request_cancel(self, request_id: str) -> bool:
        with self.request_lock:
            known = request_id in self.active_requests
            self.cancelled_requests.add(request_id)
        self.inc_stat("ws_cancelled_total")
        self.mark_request(request_id, "cancelling")
        return known

