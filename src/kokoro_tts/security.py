"""Authentication helpers for AngeVoice."""

import hmac

from fastapi import HTTPException, Request, WebSocket

from .config import TTSConfig


def _extract_bearer_token(auth: str) -> str:
    """Extract bearer token from Authorization header value (case-insensitive prefix)."""
    if auth.lower().startswith("bearer "):
        return auth[7:]
    return ""


def make_verify_api_key(cfg: TTSConfig):
    """Return a FastAPI dependency that enforces Bearer auth when configured."""

    async def verify_api_key(request: Request):
        if cfg.api_key:
            auth = request.headers.get("Authorization", "")
            token = _extract_bearer_token(auth)
            if not hmac.compare_digest(token, cfg.api_key or ""):
                raise HTTPException(status_code=401, detail="Invalid API key")

    return verify_api_key


async def verify_ws_key(cfg: TTSConfig, websocket: WebSocket, token: str = "") -> bool:
    """Validate a WebSocket token/header pair against ``KOKORO_API_KEY``."""
    if not cfg.api_key:
        return True
    auth = websocket.headers.get("authorization", "")
    header_token = _extract_bearer_token(auth)
    supplied = token or header_token
    return hmac.compare_digest(supplied, cfg.api_key or "")
