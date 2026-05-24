"""轻量自然分句器。

这里不做重型 NLP；目标是让中英文长文本在进入 TTS 模型前按自然边界切开，
避免切断英文单词、版本号/IP/小数，也避免中文用户常见的长句硬切导致卡顿。
"""

from __future__ import annotations

import re

_HARD_PUNCT = set("。！？!?；;")
_SOFT_PUNCT = set("，,、：:")
_CLOSERS = set('”’》」』）)]}】〉')
_OPENERS = set('“‘《「『（([{【〈')


def normalize_text_for_segmentation(text: str) -> str:
    """保留段落边界的温和空白归一化。"""

    value = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", value)
    value = re.sub(r"[\t\f\v ]+", " ", value)
    value = re.sub(r" *\n *", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def segment_text_natural(
    text: str,
    *,
    max_text_length: int,
    segment_length: int,
    single_newline_policy: str = "auto",
    flush_sentence_boundaries: bool = False,
) -> list[str]:
    """按自然边界切分文本，兼顾中文长句和英文长文本。

    ``single_newline_policy``：
    - ``auto``：中文网页/小说的段内硬换行尽量合并，标题/列表保留；
    - ``preserve``：每个单换行都作为 flush 点；
    - ``space``：单换行统一当空格。
    """

    normalized = normalize_text_for_segmentation(text)
    if not normalized:
        return []
    limit = max(1, int(max_text_length))
    chunk_size = max(40, int(segment_length))
    policy = str(single_newline_policy or "auto").strip().lower()
    if policy not in {"auto", "preserve", "space"}:
        policy = "auto"
    normalized = normalized[:limit]

    paragraphs = re.split(r"\n{2,}", normalized)
    segments: list[str] = []
    current = ""

    def flush_current() -> None:
        nonlocal current
        piece = current.strip()
        if piece:
            segments.append(piece)
        current = ""

    def append_unit(unit: str) -> None:
        nonlocal current
        unit = unit.strip()
        if not unit:
            return
        if current and len(current) + len(unit) + 1 > chunk_size:
            flush_current()
        if len(unit) <= chunk_size:
            current = (current + " " + unit).strip() if current and _needs_space(current, unit) else current + unit
            return
        flush_current()
        segments.extend(_split_long_unit(unit, chunk_size))

    for paragraph in paragraphs:
        lines = [line.strip() for line in paragraph.splitlines() if line.strip()]
        if not lines:
            flush_current()
            continue
        for logical_line in _logical_lines(lines, policy=policy, chunk_size=chunk_size):
            for unit in _sentence_units(logical_line):
                append_unit(unit)
                if flush_sentence_boundaries and unit.strip():
                    flush_current()
            if policy == "preserve" or _looks_like_standalone_line(logical_line):
                flush_current()
        flush_current()

    return segments or [normalized]


def _logical_lines(lines: list[str], *, policy: str, chunk_size: int) -> list[str]:
    if policy == "preserve":
        return lines
    if policy == "space":
        return [_join_text_lines(lines)]

    groups: list[str] = []
    buffer = ""

    def flush() -> None:
        nonlocal buffer
        if buffer.strip():
            groups.append(buffer.strip())
        buffer = ""

    for line in lines:
        if _looks_like_list_item(line) or _looks_like_title(line):
            flush()
            groups.append(line)
            continue
        buffer = _join_text_lines([buffer, line]) if buffer else line
        if _ends_sentence(line) and len(buffer) >= max(20, int(chunk_size * 0.45)):
            flush()
    flush()
    return groups or lines


def _join_text_lines(lines: list[str]) -> str:
    value = ""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if not value:
            value = line
        else:
            value = (value + " " + line) if _needs_space(value, line) else value + line
    return value


def _looks_like_list_item(line: str) -> bool:
    return bool(re.match(r"^(?:[-*•]|\d+[.)、]|[一二三四五六七八九十]+[、.])\s*", line))


def _looks_like_title(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) > 24:
        return False
    if _ends_sentence(stripped):
        return False
    return bool(re.search(r"[A-Za-z]", stripped)) or len(stripped) <= 8


def _looks_like_standalone_line(line: str) -> bool:
    return _looks_like_list_item(line) or _looks_like_title(line)


def _ends_sentence(line: str) -> bool:
    return bool(line) and (line[-1] in _HARD_PUNCT or line[-1] in _CLOSERS or line.endswith("..."))


def _needs_space(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if not (left[-1].isascii() and right[0].isascii()):
        return False
    if right[0] in ",.!?;:)]}”’\"'":
        return False
    if left[-1].isspace() or right[0].isspace():
        return False
    return left[-1].isalnum() or left[-1] in ".!?;:)]}”’\"'"


def _sentence_units(text: str) -> list[str]:
    units: list[str] = []
    start = 0
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        boundary = False
        if ch == "\n":
            boundary = True
        elif ch in _HARD_PUNCT:
            boundary = True
        elif ch == ".":
            boundary = _is_english_period_boundary(text, i)
        elif ch in {"…", "—"}:
            boundary = i + 1 >= n or text[i + 1] != ch
        if boundary:
            end = i + 1
            while end < n and text[end] in _CLOSERS:
                end += 1
            piece = text[start:end].strip()
            if piece:
                units.append(piece)
            start = end
            i = end
            continue
        i += 1
    tail = text[start:].strip()
    if tail:
        units.append(tail)
    return units


def _is_english_period_boundary(text: str, index: int) -> bool:
    prev_ch = text[index - 1] if index > 0 else ""
    next_ch = text[index + 1] if index + 1 < len(text) else ""
    if prev_ch.isdigit() and next_ch.isdigit():
        return False
    if prev_ch.isalnum() and next_ch.isalnum():
        return False
    prefix = text[max(0, index - 8):index + 1].lower()
    abbreviations = ("mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.", "st.", "vs.", "etc.", "e.g.", "i.e.")
    if any(prefix.endswith(item) for item in abbreviations):
        return False
    return not next_ch or next_ch.isspace() or next_ch in _CLOSERS


def _split_long_unit(text: str, chunk_size: int) -> list[str]:
    parts: list[str] = []
    remaining = text.strip()
    while len(remaining) > chunk_size:
        split_at = _best_split_index(remaining, chunk_size)
        piece = remaining[:split_at].strip()
        if piece:
            parts.append(piece)
        remaining = remaining[split_at:].lstrip()
    if remaining:
        parts.append(remaining)
    return parts


def _best_split_index(text: str, chunk_size: int) -> int:
    min_index = max(20, int(chunk_size * 0.55))
    window = text[: min(len(text), chunk_size + 1)]
    for punct_set in (_SOFT_PUNCT, set(" ")):
        for idx in range(len(window) - 1, min_index - 1, -1):
            ch = window[idx]
            if ch not in punct_set:
                continue
            if ch == " " or _safe_punct_split(text, idx):
                return idx + 1
    for idx in range(min(len(text), chunk_size), min_index - 1, -1):
        if text[idx - 1].isspace():
            return idx
    idx = min(len(text), chunk_size)
    while idx > min_index and _is_ascii_word_char(text[idx - 1]) and idx < len(text) and _is_ascii_word_char(text[idx]):
        idx -= 1
    return max(1, idx)


def _safe_punct_split(text: str, idx: int) -> bool:
    ch = text[idx]
    prev_ch = text[idx - 1] if idx > 0 else ""
    next_ch = text[idx + 1] if idx + 1 < len(text) else ""
    if ch in {",", "，", "、", ":", "："} and prev_ch.isdigit() and next_ch.isdigit():
        return False
    return True


def _is_ascii_word_char(ch: str) -> bool:
    return bool(ch) and ch.isascii() and (ch.isalnum() or ch in {"_", "-"})
