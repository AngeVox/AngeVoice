from __future__ import annotations

import pytest
from fastapi import HTTPException

from kokoro_tts.config import TTSConfig
from kokoro_tts.text.frontend import normalize_for_model
from kokoro_tts.validation import prepare_text_for_synthesis


@pytest.fixture()
def legacy_cfg() -> TTSConfig:
    return TTSConfig(angevoice_tn_engine="legacy")


@pytest.mark.parametrize(
    "source,expected",
    [
        ("AngeVoice 2.6.614 版本", "AngeVoice 2.6.614 版本"),
        ("Python 3.10", "Python 3.10"),
        ("CUDA 12.1", "CUDA 12.1"),
        ("3.5 版本", "3.5 版本"),
        ("3.5mm", "3.5mm"),
        ("今天12点", "今天十二点"),
        ("2026年", "二千零二十六年"),
        ("2026.1.10", "二零二六年一月十日"),
    ],
)
def test_2615_text_legacy_golden_outputs_across_models(legacy_cfg, source, expected):
    for model in ("kokoro", "moss", "zipvoice"):
        assert normalize_for_model(source, legacy_cfg, model=model) == expected
        assert prepare_text_for_synthesis(source, legacy_cfg, model_id=model) == expected


def test_2615_text_polyphone_proxy_is_model_isolated(legacy_cfg):
    assert prepare_text_for_synthesis("银行行长", legacy_cfg, model_id="kokoro") == "银杭杭掌"
    assert prepare_text_for_synthesis("银行行长", legacy_cfg, model_id="moss") == "银行行长"
    assert prepare_text_for_synthesis("银行行长", legacy_cfg, model_id="zipvoice") == "银行行长"


@pytest.mark.parametrize(
    "source",
    [
        "AngeVoice 2.6.614 版本",
        "Python 3.10",
        "CUDA 12.1",
        "Live2D",
        "CPU GPU RTF API TTS ZipVoice MOSS",
        "3.5mm",
    ],
)
def test_2615_text_protected_terms_remain_unmodified_by_prepare(legacy_cfg, source):
    for model in ("kokoro", "moss", "zipvoice"):
        assert prepare_text_for_synthesis(source, legacy_cfg, model_id=model) == source


@pytest.mark.parametrize(
    "source",
    [
        "https://example.com/a?b=1",
        "D:\\AI\\work\\AngeVoice-main",
        "192.168.1.2",
    ],
)
def test_2615_text_non_synthesizable_protected_spans_are_rejected_not_rewritten(legacy_cfg, source):
    for model in ("kokoro", "moss", "zipvoice"):
        assert normalize_for_model(source, legacy_cfg, model=model) == source
        with pytest.raises(HTTPException) as exc_info:
            prepare_text_for_synthesis(source, legacy_cfg, model_id=model)
        assert exc_info.value.status_code == 400
        assert exc_info.value.detail["code"] == "NO_SYNTHESIZABLE_TEXT"
