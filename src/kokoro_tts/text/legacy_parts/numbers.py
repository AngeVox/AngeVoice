"""Numeric normalization rules for the conservative legacy TN path."""

from __future__ import annotations

import re

DIGITS_ZH = {
    "0": "零",
    "1": "一",
    "2": "二",
    "3": "三",
    "4": "四",
    "5": "五",
    "6": "六",
    "7": "七",
    "8": "八",
    "9": "九",
}
DIGITS_ZH_READING = {**DIGITS_ZH, "1": "幺"}


def spell_digits(text: str, use_yao: bool = False) -> str:
    """Read a digit sequence character-by-character."""

    table = DIGITS_ZH_READING if use_yao else DIGITS_ZH
    return "".join(table.get(ch, ch) for ch in text)


def _read_under_10000(value: int) -> str:
    if value == 0:
        return "零"
    units = ["", "十", "百", "千"]
    parts: list[str] = []
    zero_pending = False
    pos = 0
    n = value

    while n > 0:
        digit = n % 10
        if digit == 0:
            if parts:
                zero_pending = True
        else:
            part = DIGITS_ZH[str(digit)] + units[pos]
            if zero_pending:
                parts.append("零")
                zero_pending = False
            parts.append(part)
        n //= 10
        pos += 1

    spoken = "".join(reversed(parts)).rstrip("零")
    if spoken.startswith("一十"):
        spoken = spoken[1:]
    return spoken or "零"


def read_small_int(value: int) -> str:
    """Read an integer in common Chinese numeric form."""

    if value < 0:
        return "负" + read_small_int(-value)
    if value < 10000:
        return _read_under_10000(value)

    group_units = ["", "万", "亿", "兆", "京"]
    groups: list[int] = []
    number = int(value)
    while number > 0:
        groups.append(number % 10000)
        number //= 10000

    if len(groups) > len(group_units):
        return spell_digits(str(value))

    parts: list[str] = []
    zero_pending = False
    for index in range(len(groups) - 1, -1, -1):
        group = groups[index]
        if group == 0:
            if parts:
                zero_pending = True
            continue
        if parts and (zero_pending or group < 1000):
            parts.append("零")
        zero_pending = False
        parts.append(_read_under_10000(group) + group_units[index])
    return "".join(parts) or "零"


def _read_decimal_amount(raw: str) -> str:
    number = raw.replace(",", "")
    integer, dot, frac = number.partition(".")
    spoken = read_small_int(int(integer))
    if dot and frac:
        spoken += "点" + spell_digits(frac)
    return spoken


def _read_money_amount(raw: str) -> str:
    number = raw.replace(",", "")
    integer, dot, frac = number.partition(".")
    spoken = read_small_int(int(integer)) + "元"
    if dot and frac:
        frac = (frac + "00")[:2]
        if frac[0] != "0":
            spoken += DIGITS_ZH[frac[0]] + "角"
        if frac[1] != "0":
            spoken += DIGITS_ZH[frac[1]] + "分"
    return spoken


def _signed_prefix(sign: str) -> str:
    return "负" if sign == "-" else ""


def _normalize_thousand_money(text: str) -> str:
    def repl_thousand_money(match: re.Match[str]) -> str:
        _prefix, sign, amount, _suffix = match.groups()
        spoken = _read_money_amount(amount)
        return ("负" if sign == "-" else "") + spoken

    return re.sub(
        r"(?<![\dA-Za-z])(¥|￥)?([+-]?)(\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?)(元)?(?![\dA-Za-z])",
        lambda m: repl_thousand_money(m) if (m.group(1) or m.group(4)) else m.group(0),
        text,
    )


def _normalize_thousand_numbers(text: str) -> str:
    def repl_thousand_number(match: re.Match[str]) -> str:
        raw = match.group(0)
        percent = raw.endswith("%")
        if percent:
            raw = raw[:-1]
        sign = ""
        if raw.startswith(("+", "-")):
            sign, raw = raw[0], raw[1:]
        try:
            spoken = _read_decimal_amount(raw)
        except ValueError:
            number = raw.replace(",", "")
            integer, dot, frac = number.partition(".")
            spoken = spell_digits(integer)
            if dot and frac:
                spoken += "点" + spell_digits(frac)
        negative = sign == "-"
        if percent:
            return ("负" if negative else "") + "百分之" + spoken
        if negative:
            spoken = "负" + spoken
        return spoken

    return re.sub(r"(?<![\dA-Za-z¥￥])[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?%?(?![\dA-Za-z])", repl_thousand_number, text)


def _normalize_money(text: str) -> str:
    def repl_money(match: re.Match[str]) -> str:
        prefix, amount, suffix = match.groups()
        if not prefix and not suffix:
            return match.group(0)
        return _read_money_amount(amount)

    return re.sub(r"(?<![\dA-Za-z])(¥|￥)?(\d{1,16}(?:\.\d{1,2})?)(元)?(?![\dA-Za-z])", repl_money, text)


def _normalize_percent(text: str) -> str:
    def repl_percent(match: re.Match[str]) -> str:
        sign = match.group(1) or ""
        value = match.group(2)
        integer, dot, frac = value.partition(".")
        try:
            spoken = read_small_int(int(integer))
        except ValueError:
            spoken = spell_digits(integer)
        if dot and frac:
            spoken += "点" + spell_digits(frac)
        return ("负" if sign == "-" else "") + "百分之" + spoken

    return re.sub(r"(?<![\dA-Za-z])([+-]?)(\d+(?:\.\d+)?)%(?!\d)", repl_percent, text)


def _normalize_mobile_numbers(text: str) -> str:
    def repl_mobile(match: re.Match[str]) -> str:
        number = match.group(0)
        return "，".join([
            spell_digits(number[:3], use_yao=True),
            spell_digits(number[3:7], use_yao=True),
            spell_digits(number[7:], use_yao=True),
        ])

    return re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", repl_mobile, text)


def _normalize_long_numbers(text: str) -> str:
    def repl_long_number(match: re.Match[str]) -> str:
        number = match.group(0)
        grouped = [number[i : i + 4] for i in range(0, len(number), 4)]
        return "，".join(spell_digits(group, use_yao=True) for group in grouped)

    return re.sub(r"(?<!\d)\d{6,}(?!\d)", repl_long_number, text)


def _normalize_plain_decimals(text: str) -> str:
    def repl_plain_decimal(match: re.Match[str]) -> str:
        before = match.string[max(0, match.start() - 6):match.start()]
        after = match.string[match.end():match.end() + 6]
        if match.string.strip() != match.group(0):
            return match.group(0)
        if before.endswith(("版本", "版", "v", "V")) or after.startswith(("版", "版本")):
            return match.group(0)
        sign = match.group(1) or ""
        integer = match.group(2)
        frac = match.group(3)
        try:
            spoken = read_small_int(int(integer))
        except ValueError:
            spoken = spell_digits(integer)
        return _signed_prefix(sign) + spoken + "点" + spell_digits(frac)

    return re.sub(r"(?<![\dA-Za-z./])([+-]?)([0-9]{1,8})\.([0-9]{1,8})(?![\dA-Za-z])", repl_plain_decimal, text)


def _normalize_trailing_number_dot(text: str) -> str:
    def repl_trailing_number_dot(match: re.Match[str]) -> str:
        sign = match.group(1) or ""
        return _signed_prefix(sign) + read_small_int(int(match.group(2)))

    return re.sub(r"(?<![\dA-Za-z./])([+-]?)([0-9]{1,5})\.(?![\dA-Za-z])", repl_trailing_number_dot, text)


def _normalize_plain_ints(text: str) -> str:
    def repl_plain_int(match: re.Match[str]) -> str:
        sign = match.group(1) or ""
        return _signed_prefix(sign) + read_small_int(int(match.group(2)))

    return re.sub(r"(?<![\dA-Za-z./])([+-]?)([0-9]{1,5})(?![\dA-Za-z./])", repl_plain_int, text)


def normalize_numeric_expressions(text: str) -> str:
    """Normalize legacy money, percentage, phone and plain-number patterns."""

    text = _normalize_thousand_money(text)
    text = _normalize_thousand_numbers(text)
    text = _normalize_money(text)
    text = _normalize_percent(text)
    text = _normalize_mobile_numbers(text)
    text = _normalize_long_numbers(text)
    text = _normalize_plain_decimals(text)
    text = _normalize_trailing_number_dot(text)
    return _normalize_plain_ints(text)
