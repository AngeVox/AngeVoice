"""Lightweight Chinese prosody and polyphone rules for TTS input."""

from __future__ import annotations

import re

try:
    from pypinyin import pinyin as _py_pinyin, Style as _py_Style
    _HAS_PYPINYIN = True
except ImportError:
    _HAS_PYPINYIN = False

_CHINESE_RE = re.compile(r"[\u4e00-\u9fff]")
_LONG_CHINESE_RUN_RE = re.compile(r"[\u4e00-\u9fff]{24,}")
_SENTENCE_END = "。！？!?"
_ANY_PUNCT = "。！？!？；;，,、：:"
_PAUSE_PUNCT = "，"

_LEXICON = {
    "往事",
    "知多少",
    "小楼",
    "昨夜",
    "又东风",
    "故国",
    "不堪",
    "回首",
    "月明中",
    "雕栏玉砌",
    "朱颜",
    "只是",
    "恰似",
    "一江春水",
    "向东流",
}
_MAX_WORD_LEN = max(len(word) for word in _LEXICON)

# ---- 每模型多音字规则 ----
# Kokoro G2P：字符替换式偏置效果较好。
# MOSS G2P：自身多音字处理较稳，大多数替换反而会破坏效果。
# 这里只添加已确认有效的 MOSS 修正。

# “春花秋月何时了”一类古诗句不再做字符替换提示。
# 之前将“了”替换为“瞭/蓼”会在部分 MOSS/Kokoro 路径里读成奇怪音，
# 默认交给上游 G2P + jieba/内置词典处理，避免为了一个 case 破坏更多文本。
_LIAO_PATTERNS_KOKORO: tuple = ()
_LIAO_PATTERNS_MOSS: tuple = ()

# 这些覆盖规则刻意保守，基于短语设计。
# 右侧使用常见同音字来偏置中文 G2P，无需在公共 API 中引入额外标记语言。
_POLYPHONE_PHRASES_KOKORO = (
    # 了: le / liao
    ("没完没了", "没完没瞭"),
    ("一了百了", "一瞭百瞭"),
    ("了然", "瞭然"),
    ("了却", "瞭却"),
    ("了结", "瞭结"),
    ("了断", "瞭断"),
    ("了悟", "瞭悟"),
    ("了无", "瞭无"),
    ("了解", "瞭解"),

    # 重: zhong / chong
    ("重庆", "虫庆"),
    ("重复", "虫复"),
    ("重新", "虫新"),
    ("重来", "虫来"),
    ("重写", "虫写"),
    ("重做", "虫做"),
    ("重启", "虫启"),
    ("重播", "虫播"),
    ("重置", "虫置"),
    ("重叠", "虫叠"),
    ("重逢", "虫逢"),
    ("重名", "虫名"),
    ("重阳", "虫阳"),

    # 行: xing / hang
    ("银行", "银杭"),
    ("行长", "杭掌"),
    ("行业", "杭业"),
    ("行情", "杭情"),
    ("行当", "杭当"),
    ("行规", "杭规"),
    ("各行各业", "各杭各业"),

    # 长: chang / zhang
    ("校长", "校掌"),
    ("院长", "院掌"),
    ("市长", "市掌"),
    ("县长", "县掌"),
    ("家长", "家掌"),
    ("班长", "班掌"),
    ("部长", "部掌"),
    ("首长", "首掌"),
    ("成长", "成掌"),
    ("长大", "掌大"),
    ("长老", "掌老"),
    ("长江", "常江"),
    ("长城", "常城"),
    ("长沙", "常沙"),
    ("长安", "常安"),
    ("长短", "常短"),
    ("长久", "常久"),
    ("长期", "常期"),
    ("长远", "常远"),
    ("长途", "常途"),

    # 乐: le / yue
    ("音乐", "音悦"),
    ("乐队", "悦队"),
    ("乐器", "悦器"),
    ("乐曲", "悦曲"),
    ("乐章", "悦章"),
    ("乐谱", "悦谱"),
    ("乐坛", "悦坛"),

    # 好: hao3 / hao4
    ("好奇", "号奇"),
    ("好学", "号学"),
    ("好客", "号客"),
    ("爱好", "爱号"),
    ("喜好", "喜号"),

    # 还: hai / huan
    ("归还", "归环"),
    ("偿还", "偿环"),
    ("还款", "环款"),
    ("还债", "环债"),
    ("还给", "环给"),

    # 都: dou / du
    ("首都", "首督"),
    ("都城", "督城"),
    ("都市", "督市"),
    ("都督", "督督"),

    # 传: chuan / zhuan
    ("传记", "撰记"),
    ("自传", "自撰"),
    ("外传", "外撰"),
    ("水浒传", "水浒撰"),

    # 数: shu / shuo
    ("数字", "树字"),
    ("数学", "树学"),
    ("数据", "树据"),
    ("数值", "树值"),
    ("函数", "函树"),
    ("次数", "次树"),
    ("数一数", "属一属"),
    ("数数", "属属"),

    # 为: wei2 / wei4
    ("因为", "因位"),
    ("为了", "位了"),
    ("为啥", "位啥"),
    ("为何", "位何"),
    ("为主", "位主"),
    ("为准", "位准"),

    # 处: chu3 / chu4
    ("处理", "楚理"),
    ("处置", "楚置"),
    ("处分", "楚分"),
    ("处罚", "楚罚"),
    ("相处", "相楚"),
    ("处方", "楚方"),
    ("处境", "楚境"),

    # 角: jiao / jue
    ("角色", "觉色"),
    ("主角", "主觉"),
    ("配角", "配觉"),
    ("名角", "名觉"),

    # 调: tiao / diao
    ("调整", "条整"),
    ("调节", "条节"),
    ("调试", "条试"),
    ("协调", "协条"),
    ("空调", "空条"),
    ("调查", "掉查"),
    ("调研", "掉研"),
    ("调动", "掉动"),
    ("调用", "掉用"),
    ("调度", "掉度"),
    ("声调", "声掉"),

    # 藏: cang / zang
    ("西藏", "西葬"),
    ("藏族", "葬族"),
    ("藏语", "葬语"),
    ("藏历", "葬历"),
    ("宝藏", "宝葬"),

    # 载: zai3 / zai4
    ("下载", "下在"),
    ("载入", "在入"),
    ("载重", "在重"),
    ("载客", "在客"),
    ("记载", "记宰"),
    ("转载", "转宰"),
    ("连载", "连宰"),

    # 曾: ceng / zeng
    ("曾经", "层经"),
    ("未曾", "未层"),
    ("曾国藩", "增国藩"),

    # 朝: chao / zhao
    ("朝代", "潮代"),
    ("王朝", "王潮"),
    ("朝廷", "潮廷"),
    ("朝着", "潮着"),
    ("朝向", "潮向"),
    ("朝阳区", "潮阳区"),
    ("朝霞", "昭霞"),
    ("朝气", "昭气"),

    # 降: jiang / xiang
    ("下降", "下匠"),
    ("降落", "匠落"),
    ("降低", "匠低"),
    ("降温", "匠温"),
    ("降价", "匠价"),
    ("投降", "投祥"),
    ("降服", "祥服"),

    # 便: bian / pian
    ("方便", "方变"),
    ("随便", "随变"),
    ("便捷", "变捷"),
    ("便利", "变利"),
    ("便宜", "骈宜"),

    # 薄: bo / bao
    ("薄荷", "播荷"),
    ("薄片", "包片"),
    ("薄饼", "包饼"),
    ("薄纸", "包纸"),

    # 卷: juan3 / juan4
    ("试卷", "试倦"),
    ("答卷", "答倦"),
    ("考卷", "考倦"),
    ("卷宗", "倦宗"),
    ("卷轴", "倦轴"),

    # 强: qiang2 / qiang3 / jiang4
    ("强迫", "抢迫"),
    ("强求", "抢求"),
    ("强词夺理", "抢词夺理"),
    ("勉强", "勉抢"),
    ("倔强", "倔匠"),

    # 少: shao3 / shao4
    ("少年", "哨年"),
    ("少女", "哨女"),
    ("少爷", "哨爷"),
    ("少校", "哨校"),

    # 差: cha / chai / ci
    ("出差", "出钗"),
    ("差遣", "钗遣"),
    ("参差", "参呲"),

    # 解: jie / xie
    ("押解", "押谢"),
    ("解数", "谢数"),

    # 露: lu / lou
    ("露出", "漏出"),
    ("露脸", "漏脸"),
    ("露馅", "漏馅"),
    ("露一手", "漏一手"),

    # 率: lv / shuai
    ("效率", "效律"),
    ("概率", "概律"),
    ("频率", "频律"),
    ("汇率", "汇律"),
    ("利率", "利律"),
    ("率先", "帅先"),
    ("率领", "帅领"),

    # 专有名词及其他常见例外。
    ("柏林", "伯林"),
    ("厦门", "夏门"),
    ("大厦", "大煞"),
    ("猪圈", "猪倦"),
    ("羊圈", "羊倦"),
    ("圈养", "倦养"),
)

# MOSS：暂空——其 G2P 自身处理多音字较好。
# 后续如需补充，可在此添加已确认的修正。
_POLYPHONE_PHRASES_MOSS: tuple = ()

# 正则覆盖规则属于语法级别（只→支, 地→的），适用于所有模型。
_REGEX_OVERRIDES = (
    (re.compile(r"([一二两三四五六七八九十百千万0-9]+)只(?=[\u4e00-\u9fff])"), r"\1支"),
    (
        re.compile(r"(高兴|认真|慢慢|轻轻|悄悄|偷偷|快速|努力|开心|难过|小心|仔细|安静|静静)地(?=[\u4e00-\u9fff])"),
        r"\1的",
    ),
)


def _has_chinese(text: str) -> bool:
    return bool(_CHINESE_RE.search(text))


def _ends_with_sentence_punctuation(text: str) -> bool:
    return bool(text) and text[-1] in _SENTENCE_END


def _contains_pause(text: str) -> bool:
    return any(ch in _ANY_PUNCT for ch in text)


def _fallback_cut(run: str) -> list[str]:
    words: list[str] = []
    index = 0
    while index < len(run):
        matched = ""
        for size in range(min(_MAX_WORD_LEN, len(run) - index), 1, -1):
            candidate = run[index : index + size]
            if candidate in _LEXICON:
                matched = candidate
                break
        if matched:
            words.append(matched)
            index += len(matched)
        else:
            words.append(run[index])
            index += 1
    return words


def segment_chinese_words(run: str) -> list[str]:
    """Segment a Chinese run using jieba when available, with a small fallback."""
    try:
        import jieba

        words = [word for word in jieba.cut(run, HMM=True) if word.strip()]
        return words or [run]
    except Exception:
        return _fallback_cut(run)


def _chunk_words(words: list[str], max_chars: int = 16) -> list[str]:
    chunks: list[str] = []
    current = ""
    for word in words:
        if current and len(current) + len(word) > max_chars:
            chunks.append(current)
            current = word
        else:
            current += word
    if current:
        chunks.append(current)
    return chunks


def _punctuate_long_run(match: re.Match[str]) -> str:
    run = match.group(0)
    chunks = _chunk_words(segment_chinese_words(run))
    return _PAUSE_PUNCT.join(chunks)


def apply_auto_punctuation(text: str) -> str:
    """Add conservative pause marks for long or poetry-like Chinese input."""
    if not _has_chinese(text):
        return text

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in normalized.split("\n") if line.strip()]
    if len(lines) > 1:
        punctuated_lines: list[str] = []
        for index, line in enumerate(lines):
            if _ends_with_sentence_punctuation(line) or line[-1:] in "，,；;":
                punctuated_lines.append(line)
            elif index == len(lines) - 1:
                punctuated_lines.append(line + "。")
            else:
                punctuated_lines.append(line + "，")
        normalized = "".join(punctuated_lines)

    normalized = _LONG_CHINESE_RUN_RE.sub(_punctuate_long_run, normalized)
    return normalized


def _is_moss_model(model: str) -> bool:
    """Check if model identifier refers to a MOSS engine."""
    return str(model or "").lower().startswith("moss")


def apply_polyphone_overrides(text: str, model: str = "kokoro") -> str:
    """Bias common Chinese polyphones toward the intended reading.

    For Kokoro: uses character-replacement biasing (reliable).
    For MOSS: skips replacements (MOSS has its own G2P).
    """
    if not _has_chinese(text):
        return text

    is_moss = _is_moss_model(model)

    # 根据模型选择对应的规则集
    phrases = _POLYPHONE_PHRASES_MOSS if is_moss else _POLYPHONE_PHRASES_KOKORO
    liao_patterns = _LIAO_PATTERNS_MOSS if is_moss else _LIAO_PATTERNS_KOKORO

    for source, target in phrases:
        text = text.replace(source, target)
    # 正则覆盖规则属于语法级别，适用于所有模型
    for pattern, replacement in _REGEX_OVERRIDES:
        text = pattern.sub(replacement, text)
    padded = text + "$"
    for pattern, replacement in liao_patterns:
        padded = pattern.sub(replacement, padded)
    return padded[:-1]


def normalize_chinese_rules(text: str, model: str = "kokoro") -> str:
    text = apply_auto_punctuation(text)
    return apply_polyphone_overrides(text, model=model)


def detect_polyphones(text: str) -> list[dict]:
    """Detect polyphone characters in text using pypinyin.

    Returns a list of dicts with character, position, and possible readings.
    Useful for debugging and admin tools.
    """
    if not _HAS_PYPINYIN or not _has_chinese(text):
        return []

    results = []
    for i, char in enumerate(text):
        if not _CHINESE_RE.match(char):
            continue
        try:
            readings = _py_pinyin(char, style=_py_Style.TONE3, heteronym=True)
            if readings and len(readings[0]) > 1:
                # 此字有多个读音（多音字）
                results.append({
                    "char": char,
                    "position": i,
                    "readings": readings[0],
                    "context": text[max(0, i - 3):i + 4],
                })
        except Exception:
            pass
    return results
