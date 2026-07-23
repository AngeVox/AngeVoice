"""Small immutable ENV declarations shared by compatibility parser seams."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class EnvIntDeclaration:
    """An integer ENV mapping without defaults or execution behavior."""

    env_name: str
    attr: str
    min_value: int | None = None
    max_value: int | None = None


CACHE_INT_DECLARATIONS = (
    EnvIntDeclaration("KOKORO_CACHE_MAX_ITEMS", "cache_max_items", 0),
    EnvIntDeclaration("KOKORO_CACHE_MAX_BYTES", "cache_max_bytes", 0),
    EnvIntDeclaration(
        "KOKORO_CACHE_SKIP_TEXT_OVER_CHARS", "cache_skip_text_over_chars", 0
    ),
    EnvIntDeclaration(
        "KOKORO_CACHE_SKIP_AUDIO_OVER_BYTES", "cache_skip_audio_over_bytes", 0
    ),
)

BATCH_INT_DECLARATIONS = (
    EnvIntDeclaration("KOKORO_BATCH_MAX_ITEMS", "batch_max_items", 1),
    EnvIntDeclaration("KOKORO_BATCH_CONCURRENCY", "batch_concurrency", 1),
)


_logger = logging.getLogger(__name__)
WarningSink = Callable[..., object]


def parse_int_env(
    name: str,
    default: int,
    *,
    warning_sink: WarningSink | None = None,
) -> int:
    """Read an integer ENV value while preserving legacy fallback semantics."""

    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        (warning_sink or _logger.warning)("忽略无效整数环境变量 %s=%r", name, value)
        return default


@dataclass(frozen=True, slots=True)
class UpdateCheckEnvDeclaration:
    """A stable Update Check ENV mapping without defaults or behavior."""

    env_name: str
    attr: str
    family: Literal["str", "float", "bool"]
    min_value: float | None = None
    max_value: float | None = None


UPDATE_CHECK_ENV_DECLARATIONS = (
    UpdateCheckEnvDeclaration(
        "ANGEVOICE_UPDATE_CHECK_ENABLED", "update_check_enabled", "bool"
    ),
    UpdateCheckEnvDeclaration(
        "ANGEVOICE_UPDATE_REPOSITORY", "update_repository", "str"
    ),
    UpdateCheckEnvDeclaration(
        "ANGEVOICE_UPDATE_CHECK_TIMEOUT_SECONDS",
        "update_check_timeout_seconds",
        "float",
        0.2,
        10.0,
    ),
    UpdateCheckEnvDeclaration(
        "ANGEVOICE_UPDATE_CHECK_CACHE_SECONDS",
        "update_check_cache_seconds",
        "float",
        0.0,
        604800.0,
    ),
)


__all__ = [
    "BATCH_INT_DECLARATIONS",
    "CACHE_INT_DECLARATIONS",
    "EnvIntDeclaration",
    "parse_int_env",
    "UPDATE_CHECK_ENV_DECLARATIONS",
    "UpdateCheckEnvDeclaration",
]
