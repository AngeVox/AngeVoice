"""Immutable defaults and validation projections for Rate Limit configuration.

ENV and Admin modules consume these declarations without moving parsing or UI
behavior here. Profile, worker, middleware, retry, and sentinel policy remain
with their existing owners.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class RateLimitValidationMetadata:
    """Existing ENV and Admin numeric validation for one Rate Limit field."""

    env_name: str
    env_min_value: float | int | None
    env_max_value: float | int | None
    admin_min_value: float | int
    admin_max_value: float | int
    admin_step: float | int


_RATE_LIMIT_VALIDATION_BY_KEY = MappingProxyType(
    {
        "rate_limit_qps": RateLimitValidationMetadata(
            env_name="KOKORO_RATE_LIMIT_QPS",
            env_min_value=0.0,
            env_max_value=None,
            admin_min_value=0,
            admin_max_value=1000,
            admin_step=0.1,
        ),
        "rate_limit_burst": RateLimitValidationMetadata(
            env_name="KOKORO_RATE_LIMIT_BURST",
            env_min_value=0,
            env_max_value=None,
            admin_min_value=0,
            admin_max_value=10000,
            admin_step=1,
        ),
    }
)


@dataclass(frozen=True, slots=True)
class RateLimitConfigMetadata:
    """One flat Rate Limit facade declaration and its default."""

    key: str
    annotation: type[float] | type[int]
    default: float | int

    @property
    def validation(self) -> RateLimitValidationMetadata:
        """Return the immutable validation projection for this field."""

        return _RATE_LIMIT_VALIDATION_BY_KEY[self.key]


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
    "RateLimitValidationMetadata",
]
