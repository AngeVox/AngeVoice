"""Authentication helpers for AngeVoice."""

import hashlib
import hmac
import secrets
import time
from http.cookies import SimpleCookie

from fastapi import HTTPException, Request, WebSocket

from .config import TTSConfig
from .config_api_key import effective_api_key

API_SESSION_COOKIE = "angevoice_api_session"
API_SESSION_MAX_AGE_SECONDS = 30 * 24 * 60 * 60


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


def _constant_time_equal(left: object, right: object) -> bool:
    """支持 Unicode 输入的 timing-safe 比较；非法值一律视为不匹配。"""
    try:
        return hmac.compare_digest(str(left if left is not None else "").encode("utf-8"), str(right if right is not None else "").encode("utf-8"))
    except Exception:
        return False


def _api_session_signature(expected_key: str, expires_at: int, nonce: str) -> str:
    payload = f"{expires_at}.{nonce}".encode("utf-8")
    return hmac.new(str(expected_key).encode("utf-8"), payload, hashlib.sha256).hexdigest()


def create_api_session_cookie(expected_key: str, *, now: float | None = None) -> str:
    """Create a browser session token without storing the API key in JavaScript."""

    current = time.time() if now is None else float(now)
    expires_at = int(current + API_SESSION_MAX_AGE_SECONDS)
    nonce = secrets.token_urlsafe(18)
    signature = _api_session_signature(expected_key, expires_at, nonce)
    return f"v1.{expires_at}.{nonce}.{signature}"


def verify_api_session_cookie(value: str, expected_key: str, *, now: float | None = None) -> bool:
    parts = str(value or "").split(".")
    if len(parts) != 4 or parts[0] != "v1":
        return False
    try:
        expires_at = int(parts[1])
    except ValueError:
        return False
    current = time.time() if now is None else float(now)
    if expires_at <= int(current):
        return False
    nonce = parts[2]
    signature = parts[3]
    if not nonce or not signature:
        return False
    return _constant_time_equal(signature, _api_session_signature(expected_key, expires_at, nonce))


def _cookie_from_header(header_value: str, name: str) -> str:
    if not header_value:
        return ""
    try:
        cookie = SimpleCookie()
        cookie.load(header_value)
        morsel = cookie.get(name)
        return morsel.value if morsel is not None else ""
    except Exception:
        return ""


def make_verify_api_key(cfg: TTSConfig):
    """Return a FastAPI dependency that enforces Bearer auth when configured."""

    async def verify_api_key(request: Request):
        expected_key = effective_api_key(cfg)
        if expected_key:
            auth = request.headers.get("Authorization", "")
            token = _extract_bearer_token(auth)
            if _constant_time_equal(token, expected_key):
                return
            cookies = getattr(request, "cookies", {}) or {}
            if verify_api_session_cookie(cookies.get(API_SESSION_COOKIE, ""), expected_key):
                return
            raise HTTPException(status_code=401, detail="Invalid or missing API key")

    return verify_api_key


async def verify_ws_key(cfg: TTSConfig, websocket: WebSocket, token: str = "") -> bool:
    """Validate WebSocket credentials against ``KOKORO_API_KEY``.

    Query-string tokens and Authorization Bearer tokens are treated as
    alternative credentials so mixed clients/proxies remain compatible during
    token rotation and reconnect flows.
    """
    expected_key = effective_api_key(cfg)
    if not expected_key:
        return True

    auth = websocket.headers.get("authorization", "")
    header_token = _extract_bearer_token(auth)

    supplied_tokens = []
    if token:
        supplied_tokens.append(token)
    if header_token and header_token not in supplied_tokens:
        supplied_tokens.append(header_token)

    if supplied_tokens and any(_constant_time_equal(candidate, expected_key) for candidate in supplied_tokens):
        return True

    cookie_value = _cookie_from_header(websocket.headers.get("cookie", ""), API_SESSION_COOKIE)
    return verify_api_session_cookie(cookie_value, expected_key)
