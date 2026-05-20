"""Shared admin authentication helpers."""

from __future__ import annotations

import base64
import binascii
import os
import secrets

from fastapi import HTTPException, Request


def admin_username() -> str:
    return os.environ.get("ANGEVOICE_ADMIN_USERNAME", "admin") or "admin"


def admin_password() -> str:
    return os.environ.get("ANGEVOICE_ADMIN_PASSWORD", "") or ""


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


def safe_compare(left: str, right: str) -> bool:
    return any(
        safe_compare_bytes(candidate, expected)
        for candidate in candidate_encodings(left)
        for expected in candidate_encodings(right)
    )


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



def auth_headers() -> dict[str, str]:
    return {"WWW-Authenticate": 'Basic realm="AngeVoice Admin", charset="UTF-8"'}


def make_verify_admin(cfg):
    """Return a dependency/callable shared by HTML admin and extra admin APIs."""

    async def verify_admin(request: Request) -> None:
        if not cfg.admin_enabled:
            raise HTTPException(status_code=404, detail="管理后台未启用")
        expected_password = admin_password()
        if not expected_password:
            raise HTTPException(status_code=503, detail="未配置管理后台密码")

        auth = request.headers.get("Authorization", "")
        parsed = parse_basic_header(auth)
        if parsed is None:
            raise HTTPException(status_code=401, detail="需要登录", headers=auth_headers())

        supplied_username, supplied_password = parsed
        username_ok = any(safe_compare_bytes(supplied_username, item) for item in candidate_encodings(admin_username()))
        password_ok = any(safe_compare_bytes(supplied_password, item) for item in candidate_encodings(expected_password))
        if not (username_ok and password_ok):
            raise HTTPException(status_code=401, detail="账号或密码错误", headers=auth_headers())

    return verify_admin
