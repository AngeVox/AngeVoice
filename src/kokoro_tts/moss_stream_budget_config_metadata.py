from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from .config_env_domain import (
    EnvFloatDeclaration,
    MOSS_STREAM_BUDGET_ENV_DECLARATIONS,
)


@dataclass(frozen=True, slots=True)
class MossStreamBudgetConfigMetadata:
    key: str
    annotation: type[float]
    default: float
    env_declaration: EnvFloatDeclaration


_MOSS_STREAM_BUDGET_ENV_BY_KEY = MappingProxyType(
    {
        declaration.attr: declaration
        for declaration in MOSS_STREAM_BUDGET_ENV_DECLARATIONS
    }
)


MOSS_STREAM_BUDGET_CONFIG_METADATA = (
    MossStreamBudgetConfigMetadata(
        key="moss_stream_budget_threshold_low",
        annotation=float,
        default=0.25,
        env_declaration=_MOSS_STREAM_BUDGET_ENV_BY_KEY[
            "moss_stream_budget_threshold_low"
        ],
    ),
    MossStreamBudgetConfigMetadata(
        key="moss_stream_budget_threshold_mid",
        annotation=float,
        default=0.65,
        env_declaration=_MOSS_STREAM_BUDGET_ENV_BY_KEY[
            "moss_stream_budget_threshold_mid"
        ],
    ),
    MossStreamBudgetConfigMetadata(
        key="moss_stream_budget_threshold_high",
        annotation=float,
        default=1.20,
        env_declaration=_MOSS_STREAM_BUDGET_ENV_BY_KEY[
            "moss_stream_budget_threshold_high"
        ],
    ),
    MossStreamBudgetConfigMetadata(
        key="moss_stream_chunk_min_floor",
        annotation=float,
        default=0.10,
        env_declaration=_MOSS_STREAM_BUDGET_ENV_BY_KEY[
            "moss_stream_chunk_min_floor"
        ],
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
