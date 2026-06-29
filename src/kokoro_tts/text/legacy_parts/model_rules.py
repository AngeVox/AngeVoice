"""Model-specific legacy text rules."""

from __future__ import annotations

from ...zh_rules import normalize_chinese_rules


def apply_model_rules(text: str, model: str) -> str:
    return normalize_chinese_rules(text, model=model)
