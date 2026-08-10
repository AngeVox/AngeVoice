"""Immutable declaration metadata for the flat Cache configuration surface.

This module owns declarations only. ENV parsing and application remain with
``config_env`` and ``config_env_domain``; runtime and Admin behavior remain in
their existing owners.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from .config_env_domain import CACHE_INT_DECLARATIONS, EnvIntDeclaration


@dataclass(frozen=True, slots=True)
class CacheAdminMetadata:
    """Admin projection data for a Cache field, when currently writable."""

    group: str
    type: str
    min_value: int | None
    max_value: int | None
    step: int | None
    restart: bool = False
    rebuild_moss: bool = False
    advanced: bool = False


@dataclass(frozen=True, slots=True)
class CacheConfigMetadata:
    """One flat Cache facade declaration and its existing projections."""

    key: str
    annotation: type[bool] | type[int]
    default: bool | int
    env_name: str
    env_declaration: EnvIntDeclaration | None
    admin: CacheAdminMetadata | None


_CACHE_INT_BY_KEY = MappingProxyType(
    {declaration.attr: declaration for declaration in CACHE_INT_DECLARATIONS}
)


CACHE_CONFIG_METADATA = (
    CacheConfigMetadata(
        key="cache_enabled",
        annotation=bool,
        default=True,
        env_name="KOKORO_CACHE_ENABLED",
        env_declaration=None,
        admin=None,
    ),
    CacheConfigMetadata(
        key="cache_max_items",
        annotation=int,
        default=64,
        env_name=_CACHE_INT_BY_KEY["cache_max_items"].env_name,
        env_declaration=_CACHE_INT_BY_KEY["cache_max_items"],
        admin=CacheAdminMetadata(
            group="service",
            type="int",
            min_value=0,
            max_value=2000,
            step=1,
        ),
    ),
    CacheConfigMetadata(
        key="cache_max_bytes",
        annotation=int,
        default=512 * 1024 * 1024,
        env_name=_CACHE_INT_BY_KEY["cache_max_bytes"].env_name,
        env_declaration=_CACHE_INT_BY_KEY["cache_max_bytes"],
        admin=CacheAdminMetadata(
            group="service",
            type="int",
            min_value=0,
            max_value=8 * 1024 * 1024 * 1024,
            step=1024 * 1024,
        ),
    ),
    CacheConfigMetadata(
        key="cache_skip_text_over_chars",
        annotation=int,
        default=1200,
        env_name=_CACHE_INT_BY_KEY["cache_skip_text_over_chars"].env_name,
        env_declaration=_CACHE_INT_BY_KEY["cache_skip_text_over_chars"],
        admin=CacheAdminMetadata(
            group="service",
            type="int",
            min_value=0,
            max_value=100000,
            step=100,
        ),
    ),
    CacheConfigMetadata(
        key="cache_skip_audio_over_bytes",
        annotation=int,
        default=20 * 1024 * 1024,
        env_name=_CACHE_INT_BY_KEY["cache_skip_audio_over_bytes"].env_name,
        env_declaration=_CACHE_INT_BY_KEY["cache_skip_audio_over_bytes"],
        admin=CacheAdminMetadata(
            group="service",
            type="int",
            min_value=0,
            max_value=2147483647,
            step=1024 * 1024,
        ),
    ),
)

CACHE_CONFIG_BY_KEY = MappingProxyType(
    {metadata.key: metadata for metadata in CACHE_CONFIG_METADATA}
)


__all__ = [
    "CACHE_CONFIG_BY_KEY",
    "CACHE_CONFIG_METADATA",
    "CacheAdminMetadata",
    "CacheConfigMetadata",
]
