"""Domain helpers for legacy text normalization."""

from __future__ import annotations

from .date_time import normalize_calendar_dates, normalize_clock_times, normalize_short_month_day
from .model_rules import apply_model_rules
from .numbers import normalize_numeric_expressions, read_small_int, spell_digits
from .protection import preserve_protected_spans
from .punctuation import normalize_punctuation
from .technical import normalize_technical_terms

__all__ = [
    "apply_model_rules",
    "normalize_calendar_dates",
    "normalize_clock_times",
    "normalize_numeric_expressions",
    "normalize_punctuation",
    "normalize_short_month_day",
    "normalize_technical_terms",
    "preserve_protected_spans",
    "read_small_int",
    "spell_digits",
]
