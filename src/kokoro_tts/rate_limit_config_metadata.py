"""Immutable defaults for the flat Rate Limit configuration surface.

This declaration-only owner contains no ENV, Admin, profile, worker, or
middleware policy. Those behaviors remain with their existing modules.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class RateLimitConfigMetadata:
    """One flat Rate Limit facade declaration and its default."""

    key: str
    annotation: type[float] | type[int]
    default: float | int


RATE_LIMIT_CONFIG_METADATA = (
    RateLimitConfigMetadata(
        key="rate_limit_qps",
        annotation=float,
        default=10.0,
    ),
    RateLimitConfigMetadata(
        key="rate_limit_burst",
        annotation=int,
        default=20,
    ),
)

RATE_LIMIT_CONFIG_BY_KEY = MappingProxyType(
    {metadata.key: metadata for metadata in RATE_LIMIT_CONFIG_METADATA}
)


__all__ = [
    "RATE_LIMIT_CONFIG_BY_KEY",
    "RATE_LIMIT_CONFIG_METADATA",
    "RateLimitConfigMetadata",
]
