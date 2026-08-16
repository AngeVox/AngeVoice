from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class MossStreamBudgetConfigMetadata:
    key: str
    annotation: type[float]
    default: float


MOSS_STREAM_BUDGET_CONFIG_METADATA = (
    MossStreamBudgetConfigMetadata(
        key="moss_stream_budget_threshold_low",
        annotation=float,
        default=0.25,
    ),
    MossStreamBudgetConfigMetadata(
        key="moss_stream_budget_threshold_mid",
        annotation=float,
        default=0.65,
    ),
    MossStreamBudgetConfigMetadata(
        key="moss_stream_budget_threshold_high",
        annotation=float,
        default=1.20,
    ),
    MossStreamBudgetConfigMetadata(
        key="moss_stream_chunk_min_floor",
        annotation=float,
        default=0.10,
    ),
)

MOSS_STREAM_BUDGET_CONFIG_BY_KEY = MappingProxyType(
    {
        metadata.key: metadata
        for metadata in MOSS_STREAM_BUDGET_CONFIG_METADATA
    }
)

__all__ = [
    "MOSS_STREAM_BUDGET_CONFIG_BY_KEY",
    "MOSS_STREAM_BUDGET_CONFIG_METADATA",
    "MossStreamBudgetConfigMetadata",
]
