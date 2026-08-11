"""Immutable declarations for the flat Update Check configuration surface.

ENV parsing, worker projection, Admin/runtime ownership, and UpdateChecker
behavior remain in their existing modules.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from .config_env_domain import (
    UPDATE_CHECK_ENV_DECLARATIONS,
    UpdateCheckEnvDeclaration,
)


@dataclass(frozen=True, slots=True)
class UpdateCheckConfigMetadata:
    """One flat Update Check facade declaration and its existing ENV seam."""

    key: str
    annotation: type[bool] | type[str] | type[float]
    default: bool | str | float
    env_declaration: UpdateCheckEnvDeclaration


_UPDATE_CHECK_ENV_BY_KEY = MappingProxyType(
    {
        declaration.attr: declaration
        for declaration in UPDATE_CHECK_ENV_DECLARATIONS
    }
)


UPDATE_CHECK_CONFIG_METADATA = (
    UpdateCheckConfigMetadata(
        key="update_check_enabled",
        annotation=bool,
        default=True,
        env_declaration=_UPDATE_CHECK_ENV_BY_KEY["update_check_enabled"],
    ),
    UpdateCheckConfigMetadata(
        key="update_repository",
        annotation=str,
        default="angevox/AngeVoice",
        env_declaration=_UPDATE_CHECK_ENV_BY_KEY["update_repository"],
    ),
    UpdateCheckConfigMetadata(
        key="update_check_timeout_seconds",
        annotation=float,
        default=3.0,
        env_declaration=_UPDATE_CHECK_ENV_BY_KEY[
            "update_check_timeout_seconds"
        ],
    ),
    UpdateCheckConfigMetadata(
        key="update_check_cache_seconds",
        annotation=float,
        default=21600.0,
        env_declaration=_UPDATE_CHECK_ENV_BY_KEY["update_check_cache_seconds"],
    ),
)

UPDATE_CHECK_CONFIG_BY_KEY = MappingProxyType(
    {metadata.key: metadata for metadata in UPDATE_CHECK_CONFIG_METADATA}
)


__all__ = [
    "UPDATE_CHECK_CONFIG_BY_KEY",
    "UPDATE_CHECK_CONFIG_METADATA",
    "UpdateCheckConfigMetadata",
]
