"""Bootstrap credential selection and startup policy, without HTTP dependencies."""

from __future__ import annotations

import os
from pathlib import Path

from .config_ids import PLACEHOLDER_ADMIN_PASSWORDS


def admin_username() -> str:
    """Return the bootstrap username, retaining legacy fallback and whitespace."""
    return os.environ.get("ANGEVOICE_ADMIN_USERNAME") or os.environ.get("KOKORO_ADMIN_USERNAME") or "admin"


def admin_password() -> str:
    """Return the bootstrap password without altering authentication bytes."""
    return os.environ.get("ANGEVOICE_ADMIN_PASSWORD") or os.environ.get("KOKORO_ADMIN_PASSWORD") or "admin123"


def validate_admin_bootstrap(config, logger) -> None:
    """Check startup policy; persisted credential contents remain store-owned."""
    username = admin_username().strip()
    password = admin_password().strip()
    credentials_file = Path(getattr(config, "admin_credentials_file", "/app/credentials/admin-credentials.json")).expanduser()
    persisted_admin = credentials_file.is_file()
    first_entry_default = username == "admin" and password == "admin123"
    if config.admin_enabled and not persisted_admin and first_entry_default:
        logger.warning("管理后台当前使用首次默认凭据 admin/admin123；公网暴露前必须在安全页修改密码")
    if (
        config.admin_enabled
        and not persisted_admin
        and password.lower() in PLACEHOLDER_ADMIN_PASSWORDS
        and not first_entry_default
    ):
        raise ValueError("ANGEVOICE_ADMIN_PASSWORD is still a placeholder; use the documented first-entry default or set a strong password")
