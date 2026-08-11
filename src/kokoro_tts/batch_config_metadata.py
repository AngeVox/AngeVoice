"""Immutable declaration metadata for the flat Batch configuration surface.

This module owns declarations only. ENV parsing and application remain with
``config_env`` and ``config_env_domain``; worker, runtime, and Admin behavior
remain in their existing owners.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from .config_env_domain import BATCH_INT_DECLARATIONS, EnvIntDeclaration


@dataclass(frozen=True, slots=True)
class BatchConfigMetadata:
    """One flat Batch facade declaration and its existing ENV seam."""

    key: str
    annotation: type[bool] | type[int]
    default: bool | int
    env_name: str
    env_declaration: EnvIntDeclaration | None


_BATCH_INT_BY_KEY = MappingProxyType(
    {declaration.attr: declaration for declaration in BATCH_INT_DECLARATIONS}
)


BATCH_CONFIG_METADATA = (
    BatchConfigMetadata(
        key="batch_enabled",
        annotation=bool,
        default=True,
        env_name="KOKORO_BATCH_ENABLED",
        env_declaration=None,
    ),
    BatchConfigMetadata(
        key="batch_max_items",
        annotation=int,
        default=20,
        env_name=_BATCH_INT_BY_KEY["batch_max_items"].env_name,
        env_declaration=_BATCH_INT_BY_KEY["batch_max_items"],
    ),
    BatchConfigMetadata(
        key="batch_concurrency",
        annotation=int,
        default=1,
        env_name=_BATCH_INT_BY_KEY["batch_concurrency"].env_name,
        env_declaration=_BATCH_INT_BY_KEY["batch_concurrency"],
    ),
)

BATCH_CONFIG_BY_KEY = MappingProxyType(
    {metadata.key: metadata for metadata in BATCH_CONFIG_METADATA}
)


__all__ = [
    "BATCH_CONFIG_BY_KEY",
    "BATCH_CONFIG_METADATA",
    "BatchConfigMetadata",
]
