"""WebSocket session state helpers."""

from __future__ import annotations

from enum import Enum


class WsSessionState(str, Enum):
    CREATED = "created"
    ACCEPTED = "accepted"
    AUTHENTICATED = "authenticated"
    QUEUED = "queued"
    RUNNING = "running"
    CANCELLING = "cancelling"
    DONE = "done"
    ERROR = "error"
