"""MOSS 文本清洗与分段工具。"""

from __future__ import annotations

import re

from ..engine import normalize_text_for_tts
from ..text_segmenter import normalize_text_for_segmentation, segment_text_natural
from ..zh_rules import normalize_chinese_rules

_CHINESE_RE = re.compile(r"[\u4e00-\u9fff]")
_ASCII_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+#./:-]*")
_TECH_TOKEN_RE = re.compile(
    r"(https?://|www\.|[A-Za-z]:\\|/[^\s]+|\b\w+\.\w+\b|\b\d+(?:\.\d+){2,}\b|\b[A-Z]{2,}\b|\b[A-Za-z]+[-_][A-Za-z0-9_-]+\b)"
)

_MIXED_ENGLISH_TRANSLATIONS: tuple[tuple[str, str], ...] = (
    ("best version of yourself", "最好的自己"),
    ("work life balance", "工作生活平衡"),
    ("work-life balance", "工作生活平衡"),
    ("core competitiveness", "核心竞争力"),
    ("personal growth", "个人成长"),
    ("self reflection", "自我反思"),
    ("self-reflection", "自我反思"),
    ("deadline", "截止日期"),
    ("deadlines", "截止日期"),
    ("anxiety", "焦虑"),
    ("healthy", "健康"),
    ("better", "更好"),
    ("challenge", "挑战"),
    ("challenges", "挑战"),
    ("creativity", "创造力"),
    ("productivity", "生产力"),
    ("success", "成功"),
    ("salary", "薪资"),
    ("learning", "学习"),
)
def _phrase_to_pattern(phrase: str) -> re.Pattern[str]:
    """把英文短语转成允许空格/连字符轻微变化的正则。"""

    pieces: list[str] = []
    last_sep = False
    for char in phrase:
        if char.isspace() or char == "-":
            if not last_sep:
                pieces.append(r"[\s\-]+")
                last_sep = True
            continue
        pieces.append(re.escape(char))
        last_sep = False
    return re.compile(r"(?<![A-Za-z0-9])" + "".join(pieces) + r"(?![A-Za-z0-9])", re.IGNORECASE)


_TRANSLATION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (_phrase_to_pattern(phrase), replacement)
    for phrase, replacement in sorted(_MIXED_ENGLISH_TRANSLATIONS, key=lambda item: len(item[0]), reverse=True)
)


def _resolve_mixed_english_policy(value) -> str:
    """把中英文混合处理策略归一到 translate/preserve/spell。"""

    raw = str(value or "translate").strip().lower()
    if raw in {"0", "false", "no", "off", "n", "preserve", "keep", "none"}:
        return "preserve"
    if raw in {"spell", "letters"}:
        return "spell"
    return "translate"


def normalize_mixed_english_for_moss(text: str, *, policy="translate") -> str:
    """降低 MOSS 中英文混读失真风险。

    MOSS-Nano 在中文句子里夹较长英文单词时，容易出现长停顿、怪声或后半段
    发音漂移。默认只把常见职场/日常英文词组替换为自然中文含义；版本号、
    API 名、URL、IP 等技术 token 不会被改写。这样比逐字母拼读更适合长文
    朗读，也不会影响 Kokoro 的中英混读能力。
    """

    resolved = _resolve_mixed_english_policy(policy)
    if resolved == "preserve" or not text:
        return text
    result = str(text)
    for pattern, replacement in _TRANSLATION_PATTERNS:
        result = pattern.sub(replacement, result)
    # 例如“工作生活平衡（work-life balance）”会变成重复中文，这里合并掉。
    result = re.sub(r"([\u4e00-\u9fff]{2,16})[（(]\1[）)]", r"\1", result)
    if resolved == "spell":
        # 当前只对已知词做语义替换。未知英文保留，避免把技术名词拆坏。
        return result
    return result


def _resolve_rules_mode(value) -> str:
    """把布尔/字符串规则开关归一到 auto/true/false。"""

    raw = str(value).strip().lower()
    if raw in {"1", "true", "yes", "on", "y"}:
        return "true"
    if raw in {"0", "false", "no", "off", "n"}:
        return "false"
    return "auto"


def _text_mix_stats(text: str) -> dict[str, float | bool]:
    """估算中英文混排程度，用于避免过度文本规范化。"""

    if not text:
        return {"chinese_ratio": 0.0, "ascii_ratio": 0.0, "mixed": False, "technical": False}
    chars = [ch for ch in text if not ch.isspace()]
    total = max(1, len(chars))
    chinese = sum(1 for ch in chars if _CHINESE_RE.match(ch))
    ascii_word_chars = sum(1 for ch in chars if ch.isascii() and (ch.isalpha() or ch.isdigit() or ch in "_+#./:-"))
    has_chinese = chinese > 0
    has_ascii_words = bool(_ASCII_WORD_RE.search(text))
    technical = bool(_TECH_TOKEN_RE.search(text))
    ascii_ratio = ascii_word_chars / total
    chinese_ratio = chinese / total
    mixed = bool(has_chinese and has_ascii_words and (ascii_ratio >= 0.08 or technical))
    return {
        "chinese_ratio": chinese_ratio,
        "ascii_ratio": ascii_ratio,
        "mixed": mixed,
        "technical": technical,
    }


def should_apply_full_angevoice_rules(text: str, mode) -> bool:
    """判断 MOSS 是否应用完整 AngeVoice 中文文本规则。"""

    resolved = _resolve_rules_mode(mode)
    if resolved == "true":
        return True
    if resolved == "false":
        return False
    stats = _text_mix_stats(text)
    if stats["mixed"] or stats["technical"]:
        return False
    # 纯中文 + 数字/日期/金额不应被误判为技术混排，继续使用完整中文规则。
    if float(stats["chinese_ratio"]) > 0:
        return True
    return False


def clean_text(text: str, *, apply_angevoice_rules=True, model: str = "moss", mixed_english_policy="translate") -> str:
    """清理输入文本，并为 MOSS 自动选择温和或完整中文规则。

    ``MOSS_APPLY_ANGEVOICE_RULES=auto`` 是推荐默认值：中文为主的小说/旁白
    走完整中文数字和标点规范化；中英文混排、URL、版本号、API 名称、文件名
    等技术文本只做温和标点/多音字规则。额外的
    ``MOSS_MIXED_ENGLISH_POLICY=translate`` 会把常见英文词组转成自然中文含义，
    避免 MOSS 在长中英混排句子里出现停顿、怪声或尾部漂移。
    """

    cleaned = normalize_text_for_segmentation(text)
    if should_apply_full_angevoice_rules(cleaned, apply_angevoice_rules):
        cleaned = normalize_text_for_tts(cleaned, model=model)
    else:
        cleaned = normalize_mixed_english_for_moss(cleaned, policy=mixed_english_policy)
        cleaned = normalize_chinese_rules(cleaned, model=model)
    return normalize_text_for_segmentation(cleaned)


def segment_text(text: str, *, max_text_length: int, segment_length: int, single_newline_policy: str = "auto") -> list[str]:
    """按中英文自然标点、段落和长度拆分 MOSS 输入。"""

    return segment_text_natural(text, max_text_length=max_text_length, segment_length=segment_length, single_newline_policy=single_newline_policy)
