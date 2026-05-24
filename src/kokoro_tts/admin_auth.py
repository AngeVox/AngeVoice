"""Shared admin authentication helpers."""

from __future__ import annotations

import base64
import binascii
import os
import secrets

from fastapi import HTTPException, Request

from .admin_credentials import AdminCredentialStore


def admin_username() -> str:
    """Return the bootstrap admin username used before durable credentials exist."""
    return os.environ.get("ANGEVOICE_ADMIN_USERNAME") or os.environ.get("KOKORO_ADMIN_USERNAME") or "admin"


def admin_password() -> str:
    """Return the bootstrap administrator password with legacy env fallback."""
    return os.environ.get("ANGEVOICE_ADMIN_PASSWORD") or os.environ.get("KOKORO_ADMIN_PASSWORD") or "admin123"


def candidate_encodings(value: str) -> list[bytes]:
    candidates: list[bytes] = []
    for encoding in ("utf-8", "latin-1"):
        try:
            encoded = value.encode(encoding)
        except UnicodeEncodeError:
            continue
        if encoded not in candidates:
            candidates.append(encoded)
    return candidates


def safe_compare_bytes(left: bytes, right: bytes) -> bool:
    return secrets.compare_digest(left, right)


def _matches_encoded_value(supplied: bytes, expected_text: str) -> bool:
    """Compare against every accepted encoding without early-return timing differences."""
    matched = False
    for expected in candidate_encodings(expected_text):
        matched = safe_compare_bytes(supplied, expected) | matched
    return bool(matched)


def safe_compare(left: str, right: str) -> bool:
    matched = False
    for candidate in candidate_encodings(left):
        matched = _matches_encoded_value(candidate, right) | matched
    return bool(matched)


def parse_basic_header(auth: str) -> tuple[bytes, bytes] | None:
    if not auth.lower().startswith("basic "):
        return None
    token = auth.split(" ", 1)[1].strip()
    try:
        raw = base64.b64decode(token, validate=True)
    except (binascii.Error, ValueError):
        return None
    if b":" not in raw:
        return None
    username, password = raw.split(b":", 1)
    return username, password


def _decode_basic_component(value: bytes) -> str:
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        return value.decode("latin-1")


def auth_headers() -> dict[str, str]:
    return {"WWW-Authenticate": 'Basic realm="AngeVoice Admin", charset="UTF-8"'}


def make_verify_admin(cfg):
    """Return a verifier supporting durable hashed credentials and legacy bootstrap env."""
    credential_store = AdminCredentialStore(cfg)

    async def verify_admin(request: Request) -> None:
        if not cfg.admin_enabled:
            raise HTTPException(status_code=404, detail="管理后台未启用")

        auth = request.headers.get("Authorization", "")
        parsed = parse_basic_header(auth)
        if parsed is None:
            raise HTTPException(status_code=401, detail="需要登录", headers=auth_headers())
        supplied_username, supplied_password = parsed

        if credential_store.exists():
            valid = credential_store.verify(_decode_basic_component(supplied_username), _decode_basic_component(supplied_password))
        else:
            expected_password = admin_password()
            if not expected_password:
                raise HTTPException(status_code=503, detail="未配置管理后台密码")
            username_ok = _matches_encoded_value(supplied_username, admin_username())
            password_ok = _matches_encoded_value(supplied_password, expected_password)
            valid = username_ok and password_ok
        if not valid:
            raise HTTPException(status_code=401, detail="账号或密码错误", headers=auth_headers())

    verify_admin.credential_store = credential_store
    return verify_admin
