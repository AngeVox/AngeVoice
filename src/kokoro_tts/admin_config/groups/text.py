"""text admin configuration fields."""

from __future__ import annotations

from ..fields import AdminConfigField, field_def


FIELDS: tuple[AdminConfigField, ...] = (
    field_def(
        "angevoice_tn_engine",
        "ANGEVOICE_TN_ENGINE",
        "默认文本处理",
        "text",
        "choice",
        "wetext",
        choices=(
            ("wetext", "标准：文本规范化"),
            ("legacy", "保守：AngeVoice 2.6.613"),
            ("off", "关闭：仅基础清理"),
        ),
        help="使用 wetext runtime 进行数字、日期、时间等文本规范化；技术字符串会先做保护。Studio 可按单次请求覆盖此默认值。",
    ),
    field_def(
        "text_single_newline_policy",
        "ANGEVOICE_SINGLE_NEWLINE_POLICY",
        "单换行策略",
        "text",
        "choice",
        "auto",
        choices=(("auto", "智能合并"), ("preserve", "保留停顿"), ("space", "当作空格")),
        help="中文网页/小说复制常有硬换行；auto 会尽量合并段内换行，只保留空行段落。",    advanced=True,
    ),
    field_def(
        "moss_apply_angevoice_rules",
        "MOSS_APPLY_ANGEVOICE_RULES",
        "MOSS 文本规则",
        "text",
        "choice",
        "auto",
        choices=(("auto", "智能处理"), ("true", "完整中文规则"), ("false", "仅温和清理")),
        rebuild_moss=False,
        help="MOSS 与 Kokoro 分离处理；auto 会对 URL、版本号、API、英文缩写等混排文本保持保守。",    advanced=True,
    ),
)
