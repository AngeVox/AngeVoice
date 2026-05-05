"""Authentication helpers for AngeVoice."""

import hmac

from fastapi import HTTPException, Request, WebSocket

from .config import TTSConfig


def make_verify_api_key(cfg: TTSConfig):
    """Return a FastAPI dependency that enforces Bearer auth when configured."""

    async def verify_api_key(request: Request):
        if cfg.api_key:
            auth = request.headers.get("Authorization", "")
            token = auth.replace("Bearer ", "") if auth.startswith("Bearer ") else ""
            if not hmac.compare_digest(token, cfg.api_key or ""):
                raise HTTPException(status_code=401, detail="Invalid API key")

    return verify_api_key


async def verify_ws_key(cfg: TTSConfig, websocket: WebSocket, token: str = "") -> bool:
    """Validate a WebSocket token/header pair against ``KOKORO_API_KEY``."""
    if not cfg.api_key:
        return True
    auth = websocket.headers.get("authorization", "")
    header_token = auth.replace("Bearer ", "") if auth.startswith("Bearer ") else ""
    supplied = token or header_token
    return hmac.compare_digest(supplied, cfg.api_key or "")
