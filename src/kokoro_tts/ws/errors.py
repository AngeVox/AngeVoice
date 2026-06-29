"""WebSocket error types."""

from __future__ import annotations


class WebSocketPayloadTooLarge(ValueError):
    """入站 WebSocket JSON 消息超过配置限制时抛出。"""


class WebSocketPayloadInvalid(ValueError):
    """入站 WebSocket 帧不是 JSON 对象时抛出。"""
