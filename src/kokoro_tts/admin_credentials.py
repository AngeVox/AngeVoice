"""Persistent administrator credentials for the management console.

The bootstrap environment password is intentionally retained only for first
startup and backward compatibility. Once credentials are changed in the admin
console, authentication uses a PBKDF2-HMAC-SHA256 hash stored in the durable
credentials volume; no plaintext administrator password is written to disk.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import unicodedata
import secrets
import time
from pathlib import Path
from typing import Any

_USERNAME_ALLOWED_SYMBOLS = "_.@-"
_PASSWORD_MIN_LENGTH = 10
_PBKDF2_ITERATIONS = 260_000


def validate_admin_username(username: str) -> str:
    """Validate a human-facing administrator name while preserving Chinese support.

    Unicode letters/numbers (including Chinese) and the small ASCII separator set
    remain valid. Control characters, whitespace, emoji and punctuation outside
    the documented separators are rejected so Basic-auth logging/UI remains safe.
    """
    value = str(username or "").strip()
    if not 2 <= len(value) <= 64:
        raise ValueError("管理员用户名长度应为 2-64 个字符")
    if not value[0].isalnum():
        raise ValueError("管理员用户名需以中文、字母或数字开头")
    for ch in value:
        if ch.isalnum() or ch in _USERNAME_ALLOWED_SYMBOLS:
            continue
        category = unicodedata.category(ch)
        if category.startswith("L") or category.startswith("N"):
            continue
        raise ValueError("管理员用户名仅允许中文、字母、数字及 _ . @ -")
    return value


def validate_admin_password(password: str) -> str:
    value = str(password or "")
    if len(value) < _PASSWORD_MIN_LENGTH:
        raise ValueError(f"管理员密码长度至少 {_PASSWORD_MIN_LENGTH} 位")
    if len(value) > 256:
        raise ValueError("管理员密码长度不能超过 256 位")
    categories = sum(
        bool(test(value))
        for test in (
            lambda text: any(ch.islower() for ch in text),
            lambda text: any(ch.isupper() for ch in text),
            lambda text: any(ch.isdigit() for ch in text),
            lambda text: any(not ch.isalnum() for ch in text),
        )
    )
    if categories < 2:
        raise ValueError("管理员密码至少包含两类字符（字母、数字或符号）")
    return value


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value.encode("ascii"))


def _derive(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)


class AdminCredentialStore:
    """Atomic, durable hashed credentials owned by the application."""

    def __init__(self, cfg):
        fallback = Path("/app/credentials/admin-credentials.json")
        self.path = Path(getattr(cfg, "admin_credentials_file", fallback) or fallback).expanduser()

    def _read(self) -> dict[str, Any] | None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError, TypeError):
            return None
        return data if isinstance(data, dict) and data.get("username") and data.get("password_hash") else None

    def exists(self) -> bool:
        return self._read() is not None

    def set_credentials(self, username: str, password: str) -> dict[str, Any]:
        username = validate_admin_username(username)
        password = validate_admin_password(password)
        salt = secrets.token_bytes(24)
        digest = _derive(password, salt, _PBKDF2_ITERATIONS)
        existing = self._read() or {}
        created_at = existing.get("created_at") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        payload = {
            "schema_version": 1,
            "username": username,
            "password_algorithm": "pbkdf2_hmac_sha256",
            "password_iterations": _PBKDF2_ITERATIONS,
            "password_salt": _b64(salt),
            "password_hash": _b64(digest),
            "created_at": created_at,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        try:
            temp.chmod(0o600)
        except OSError:
            pass
        os.replace(temp, self.path)
        try:
            self.path.chmod(0o600)
        except OSError:
            pass
        return self.status()

    def verify(self, username: str, password: str) -> bool:
        data = self._read()
        if not data:
            return False
        try:
            supplied_username = str(username or "")
            expected_username = str(data["username"])
            # secrets.compare_digest on str only accepts ASCII; compare UTF-8 bytes
            # so human-facing Unicode administrator names (including Chinese)
            # remain supported without weakening constant-time equality checks.
            if not secrets.compare_digest(
                supplied_username.encode("utf-8"), expected_username.encode("utf-8")
            ):
                return False
            iterations = int(data.get("password_iterations", _PBKDF2_ITERATIONS))
            expected = _unb64(str(data["password_hash"]))
            actual = _derive(str(password or ""), _unb64(str(data["password_salt"])), iterations)
            return secrets.compare_digest(actual, expected)
        except (KeyError, TypeError, ValueError):
            return False

    def status(self) -> dict[str, Any]:
        data = self._read()
        return {
            "persisted": bool(data),
            "path": str(self.path),
            "username": str(data.get("username", "")) if data else "",
            "schema_version": data.get("schema_version") if data else None,
            "password_algorithm": data.get("password_algorithm") if data else None,
            "updated_at": data.get("updated_at") if data else None,
        }
