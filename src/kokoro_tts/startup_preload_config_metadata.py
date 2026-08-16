"""Immutable defaults for the flat Startup Preload configuration surface.

This declaration-only owner contains no ENV, Admin, worker, server, model,
asset, or process policy. Those behaviors remain with their existing owners.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class StartupPreloadConfigMetadata:
    """One flat Startup Preload facade declaration and its default."""

    key: str
    annotation: type[bool] | type[str]
    default: bool | str


STARTUP_PRELOAD_CONFIG_METADATA = (
    StartupPreloadConfigMetadata(
        key="startup_preload_enabled",
        annotation=bool,
        default=False,
    ),
    StartupPreloadConfigMetadata(
        key="startup_preload_model",
        annotation=str,
        default="kokoro",
    ),
)

STARTUP_PRELOAD_CONFIG_BY_KEY = MappingProxyType(
    {metadata.key: metadata for metadata in STARTUP_PRELOAD_CONFIG_METADATA}
)


__all__ = [
    "STARTUP_PRELOAD_CONFIG_BY_KEY",
    "STARTUP_PRELOAD_CONFIG_METADATA",
    "StartupPreloadConfigMetadata",
]
