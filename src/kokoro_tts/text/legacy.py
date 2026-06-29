"""Built-in conservative Chinese text normalization.

This module keeps AngeVoice's lightweight 2.6.x TN rules separate from model
runtime code. It intentionally covers common TTS cases only: dates, times,
amounts, percentages, phone-like long numbers, and plain numeric input.
"""

from __future__ import annotations

import re

from ..zh_rules import normalize_chinese_rules
from .legacy_parts import (
    normalize_calendar_dates,
    normalize_short_month_day,
    read_small_int,
    spell_digits,
)
from .legacy_parts import apply_model_rules as _apply_model_rules
from .legacy_parts import normalize_clock_times as _normalize_clock_times
from .legacy_parts import normalize_numeric_expressions as _normalize_numeric_expressions
from .legacy_parts import normalize_punctuation as _normalize_punctuation
from .legacy_parts import normalize_technical_terms as _normalize_technical_terms
from .legacy_parts import preserve_protected_spans as _preserve_protected_spans

__all__ = [
    "normalize_calendar_dates",
    "normalize_chinese_rules",
    "normalize_short_month_day",
    "normalize_text_for_tts",
    "read_small_int",
    "spell_digits",
]


def normalize_text_for_tts(text: str, model: str = "kokoro") -> str:
    """Normalize common Chinese TTS text patterns conservatively."""

    if not text:
        return text

    text = _preserve_protected_spans(text)
    text = _normalize_punctuation(text)
    text = _normalize_technical_terms(text)
    text = normalize_calendar_dates(text)
    text = _normalize_clock_times(text)
    text = _normalize_numeric_expressions(text)
    return _apply_model_rules(text, model=model)
