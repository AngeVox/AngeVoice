"""Date and time normalization for the conservative legacy TN path."""

from __future__ import annotations

import re

from .numbers import DIGITS_ZH, read_small_int, spell_digits

DATE_CONTEXT_BEFORE = (
    "日期", "日子", "生日", "活动", "会议", "考试", "开会", "发布", "上线", "更新",
    "维护", "开服", "截止", "截至", "预约", "计划", "预计", "定在", "改到",
    "推迟到", "提前到", "报名", "放假", "假期", "档期", "排期", "工期", "节日",
)
DATE_CONTEXT_AFTER = (
    "号", "日", "当天", "那天", "这天", "之前", "之后", "以前", "以后", "前", "后",
    "开始", "结束", "上线", "发布", "更新", "开服", "维护", "截止", "截至", "报名",
    "活动", "会议", "考试", "开会", "放假", "假期", "见", "再说",
)
DATE_CONTEXT_WORDS = ("今天", "明天", "昨天", "后天", "前天", "今年", "明年", "去年", "本月", "下月", "上月")


def _read_time_hour(value: int) -> str:
    return "两" if value == 2 else read_small_int(value)


def _read_clock_time(hour: int, minute: int) -> str:
    spoken = _read_time_hour(hour) + "点"
    if minute == 0:
        return spoken + "整"
    if minute < 10:
        return spoken + "零" + DIGITS_ZH[str(minute)] + "分"
    return spoken + read_small_int(minute) + "分"


def _read_month_day(month: int, day: int) -> str:
    return f"{read_small_int(month)}月{read_small_int(day)}日"


def _looks_like_short_date_context(text: str, start: int, end: int) -> bool:
    """Heuristically decide whether M.D / M-D means month-day."""

    before = text[max(0, start - 8):start]
    after = text[end:end + 8]
    if any(after.startswith(item) for item in DATE_CONTEXT_AFTER):
        return True
    if any(item in before for item in DATE_CONTEXT_BEFORE):
        return True
    if any(item in before or item in after for item in DATE_CONTEXT_WORDS):
        return True
    if before.endswith(("在", "于", "到", "从", "至", "距", "等到")) and not after.startswith(("版", "版本", "元", "%")):
        return True
    return False


def normalize_short_month_day(text: str) -> str:
    """Normalize contextual M.D dates before decimal processing."""

    def repl(match: re.Match[str]) -> str:
        month = int(match.group("month"))
        day = int(match.group("day"))
        if not (1 <= month <= 12 and 1 <= day <= 31):
            return match.group(0)
        if not _looks_like_short_date_context(text, match.start(), match.end()):
            return match.group(0)
        return _read_month_day(month, day)

    return re.sub(
        r"(?<![\dA-Za-z])(?P<month>1[0-2]|0?[1-9])[./-](?P<day>3[01]|[12]\d|0?[1-9])(?![\dA-Za-z])",
        repl,
        text,
    )


def normalize_calendar_dates(text: str) -> str:
    """Normalize explicit Gregorian dates without touching versions."""

    if not text:
        return text

    def repl_date(match: re.Match[str]) -> str:
        year, month, day = match.groups()
        return f"{spell_digits(year)}年{read_small_int(int(month))}月{read_small_int(int(day))}日"

    normalized = re.sub(r"(?<!\d)(20\d{2}|19\d{2})[-/.](\d{1,2})[-/.](\d{1,2})(?:[日号])?(?!\d)", repl_date, text)
    return normalize_short_month_day(normalized)


def normalize_clock_times(text: str) -> str:
    """Normalize HH:MM clock expressions."""

    def repl_time(match: re.Match[str]) -> str:
        hour = int(match.group(1))
        minute = int(match.group(2))
        return _read_clock_time(hour, minute)

    return re.sub(r"(?<!\d)([01]?\d|2[0-3])[:：]([0-5]\d)(?!\d)", repl_time, text)
