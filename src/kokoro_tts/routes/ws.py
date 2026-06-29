"""WebSocket 流式合成路由。"""

from __future__ import annotations

from contextlib import suppress

from fastapi import APIRouter, WebSocket

from ..service_state import ServiceState
from ..ws import TtsWebSocketSession, WebSocketPayloadInvalid, WebSocketPayloadTooLarge, WsSessionState

__all__ = [
    "TtsWebSocketSession",
    "WebSocketPayloadInvalid",
    "WebSocketPayloadTooLarge",
    "WsSessionState",
    "create_ws_router",
]


def create_ws_router(state: ServiceState) -> APIRouter:
    router = APIRouter()

    @router.websocket("/ws/v1/tts")
    async def ws_tts(websocket: WebSocket):
        if not await state.try_acquire_websocket_connection():
            with suppress(Exception):
                await websocket.close(code=1013, reason="WebSocket connection capacity reached")
            return
        try:
            await TtsWebSocketSession(websocket=websocket, state=state).run()
        finally:
            await state.release_websocket_connection()

    return router
