"""MOSS 文本清洗与分段工具。"""

from __future__ import annotations

import re

from ..engine import normalize_text_for_tts


def clean_text(text: str, *, apply_angevoice_rules: bool) -> str:
    """清理输入文本，并按配置应用 AngeVoice 中文规则。"""

    cleaned = re.sub(r"[\x00-\x1f\x7f]", " ", str(text or ""))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if apply_angevoice_rules:
        cleaned = normalize_text_for_tts(cleaned)
    return cleaned


def segment_text(text: str, *, max_text_length: int, segment_length: int) -> list[str]:
    """按标点和长度拆分 MOSS 输入，避免单段过长导致卡顿。"""

    if not text:
        return []
    limit = max(1, int(max_text_length))
    chunk_size = max(20, int(segment_length))
    trimmed = text[:limit]
    sentences = re.split(r"(?<=[。！？!?；;])", trimmed)
    segments: list[str] = []
    current = ""
    for sentence in sentences:
        if not sentence:
            continue
        if len(current) + len(sentence) <= chunk_size:
            current += sentence
            continue
        if current.strip():
            segments.append(current.strip())
        current = sentence
        while len(current) > chunk_size:
            segments.append(current[:chunk_size].strip())
            current = current[chunk_size:]
    if current.strip():
        segments.append(current.strip())
    return segments or [trimmed]
