"""Authentication helpers for AngeVoice."""

import hmac

from fastapi import HTTPException, Request, WebSocket

from .config import TTSConfig


def _extract_bearer_token(auth: str) -> str:
    """从 Authorization 头提取 Bearer token，支持大小写混合、前导/尾部空白。"""
    value = str(auth or "").strip()
    prefix = "bearer"
    if value.lower().startswith(prefix):
        rest = value[len(prefix):]
        # 必须有空白分隔符，防止 Bearerxxx 误通过
        if rest and rest[0].isspace():
            return rest[1:].strip()
    return ""


def make_verify_api_key(cfg: TTSConfig):
    """Return a FastAPI dependency that enforces Bearer auth when configured."""

    async def verify_api_key(request: Request):
        if cfg.api_key:
            auth = request.headers.get("Authorization", "")
            token = _extract_bearer_token(auth)
            if not hmac.compare_digest(token, cfg.api_key or ""):
                raise HTTPException(
                    status_code=401,
                    detail=(
                        "Invalid API key. Open Studio settings and paste your token; "
                        "admins can view or rotate the key in /admin when admin is enabled."
                    ),
                )

    return verify_api_key


async def verify_ws_key(cfg: TTSConfig, websocket: WebSocket, token: str = "") -> bool:
    """Validate a WebSocket token/header pair against ``KOKORO_API_KEY``."""
    if not cfg.api_key:
        return True
    auth = websocket.headers.get("authorization", "")
    header_token = _extract_bearer_token(auth)
    supplied = token or header_token
    return hmac.compare_digest(supplied, cfg.api_key or "")
