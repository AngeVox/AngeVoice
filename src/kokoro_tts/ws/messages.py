"""Inbound WebSocket message parsing."""

from __future__ import annotations

import json

from starlette.websockets import WebSocketDisconnect

from .errors import WebSocketPayloadInvalid, WebSocketPayloadTooLarge


class MessageParsingMixin:
    """Helpers for bounded JSON WebSocket input."""

    async def _receive_json_limited(self) -> dict:
        """读取 JSON 对象，同时强制执行每条消息的分配预算。

        ``run_server`` 还将此限制作为 ``ws_max_size`` 转发给 Uvicorn，
        以便正常部署在解码前拒绝大帧。此路由级保护在 TestClient
        或替代 ASGI 启动器下仍然有效。
        """
        frame = await self.websocket.receive()
        if frame.get("type") == "websocket.disconnect":
            raise WebSocketDisconnect(code=int(frame.get("code") or 1000))
        raw = frame.get("text")
        if raw is None:
            raw_bytes = frame.get("bytes") or b""
        else:
            raw_bytes = str(raw).encode("utf-8")
        limit = max(1024, int(getattr(self.cfg, "websocket_max_message_bytes", 32 * 1024 * 1024) or 32 * 1024 * 1024))
        if len(raw_bytes) > limit:
            raise WebSocketPayloadTooLarge(f"WebSocket message exceeds {limit} bytes")
        try:
            value = json.loads(raw_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WebSocketPayloadInvalid("WebSocket message must be a JSON object") from exc
        if not isinstance(value, dict):
            raise WebSocketPayloadInvalid("WebSocket message must be a JSON object")
        return value
