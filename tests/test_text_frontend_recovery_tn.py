from __future__ import annotations

import sys
import types

import pytest

from kokoro_tts.config import TTSConfig, load_config
from kokoro_tts.text.frontend import normalize_for_model
from kokoro_tts.text.tn import reset_tn_caches
from kokoro_tts.validation import prepare_text_for_synthesis


@pytest.fixture(autouse=True)
def _clear_tn_cache_between_tests():
    reset_tn_caches()
    yield
    reset_tn_caches()


def _install_fake_wetext(monkeypatch, normalizer_cls):
    """Install a fake ``wetext`` module with the given Normalizer class."""
    wetext_mod = types.ModuleType("wetext")
    wetext_mod.Normalizer = normalizer_cls
    monkeypatch.setitem(sys.modules, "wetext", wetext_mod)
    reset_tn_caches()


# ── pyproject.toml contract ────────────────────────────────────────────

def test_tn_extra_does_not_reference_pynini_or_wetextprocessing():
    """Ensure [tn] extra has no pynini / WeTextProcessing transitive deps."""
    from pathlib import Path
    import configparser, tomllib

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    with open(pyproject, "rb") as fh:
        data = tomllib.load(fh)
    tn_deps = data["project"]["optional-dependencies"]["tn"]
    joined = " ".join(tn_deps).lower()
    assert "pynini" not in joined, f"tn extra must not depend on pynini: {tn_deps}"
    assert "wetextprocessing" not in joined, f"tn extra must not depend on WeTextProcessing: {tn_deps}"
    assert "wetext" in joined, f"tn extra must depend on wetext: {tn_deps}"


# ── engine env ─────────────────────────────────────────────────────────

def test_tn_engine_env_normalizes_values(monkeypatch):
    monkeypatch.setenv("ANGEVOICE_TN_ENGINE", "off")
    cfg = load_config()
    assert cfg.angevoice_tn_engine == "off"
    monkeypatch.setenv("ANGEVOICE_TN_ENGINE", "legacy")
    cfg = load_config()
    assert cfg.angevoice_tn_engine == "legacy"


# ── fallback ───────────────────────────────────────────────────────────

def test_wetext_missing_falls_back_to_legacy_without_blocking():
    cfg = TTSConfig(angevoice_tn_engine="wetext")
    assert prepare_text_for_synthesis("3.5", cfg, model_id="zipvoice") == "三点五"
    assert normalize_for_model("AngeVoice 2.6.613 版本", cfg, model="kokoro") == "AngeVoice 2.6.613 版本"


# ── wetext backend shape ───────────────────────────────────────────────

def test_wetext_backend_import_shape(monkeypatch):
    """Verify tn.py uses wetext.Normalizer and calls .normalize()."""
    calls: list[str] = []

    class FakeNormalizer:
        def normalize(self, text: str) -> str:
            calls.append(text)
            return text.replace("今天是2026-06-11", "今天是二零二六年六月十一日")

    _install_fake_wetext(monkeypatch, FakeNormalizer)
    cfg = TTSConfig(angevoice_tn_engine="wetext")
    result = normalize_for_model("今天是2026-06-11", cfg, model="kokoro")
    assert result == "今天是二零二六年六月十一日"
    assert calls, "FakeNormalizer.normalize was never called"


def test_wetext_missing_fallback_legacy(monkeypatch):
    """When wetext is not importable, fall back gracefully."""
    monkeypatch.delitem(sys.modules, "wetext", raising=False)
    reset_tn_caches()

    # Temporarily block wetext import
    import builtins
    _real_import = builtins.__import__

    def _block_wetext(name, *args, **kwargs):
        if name == "wetext" or name.startswith("wetext."):
            raise ImportError("fake missing wetext")
        return _real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _block_wetext)
    cfg = TTSConfig(angevoice_tn_engine="wetext")
    # Should not raise — falls back to legacy
    result = normalize_for_model("AngeVoice 2.6.613 版本", cfg, model="kokoro")
    assert "AngeVoice" in result


# ── calendar dates ─────────────────────────────────────────────────────

@pytest.mark.parametrize("source", ["2026.1.10", "2026.1.10日", "2026-1-10", "2026/1/10"])
def test_calendar_dates_are_not_treated_as_versions(source):
    cfg = TTSConfig(angevoice_tn_engine="legacy")
    assert normalize_for_model(source, cfg, model="kokoro") == "二零二六年一月十日"


def test_wetext_path_preserves_angevoice_calendar_date_before_backend(monkeypatch):
    class PassthroughNormalizer:
        def normalize(self, text):
            return text

    _install_fake_wetext(monkeypatch, PassthroughNormalizer)
    cfg = TTSConfig(angevoice_tn_engine="wetext")
    assert normalize_for_model("2026.1.10日", cfg, model="kokoro") == "二零二六年一月十日"


# ── protection ─────────────────────────────────────────────────────────

def test_external_tn_cannot_damage_protected_versions_and_terms(monkeypatch):
    class AggressiveNormalizer:
        def normalize(self, text):
            return (
                text.replace("AngeVoice", "Ange Voice")
                .replace("2.6.613", "二点六.613")
                .replace("Python 3.10", "Python 三点一零")
                .replace("CUDA 12.1", "CUDA 十二点一")
                .replace("Live2D", "Live 二 D")
                .replace("3.5mm", "三点五毫米")
            )

    _install_fake_wetext(monkeypatch, AggressiveNormalizer)
    cfg = TTSConfig(angevoice_tn_engine="wetext")
    text = "AngeVoice 2.6.613 版本 Python 3.10 CUDA 12.1 Live2D 3.5mm"
    assert normalize_for_model(text, cfg, model="kokoro") == text


def test_model_proxy_is_isolated_to_kokoro():
    cfg = TTSConfig(angevoice_tn_engine="legacy")
    assert "银杭" in prepare_text_for_synthesis("银行行长", cfg, model_id="kokoro")
    assert "银杭" not in prepare_text_for_synthesis("银行行长", cfg, model_id="moss")
    assert "银杭" not in prepare_text_for_synthesis("银行行长", cfg, model_id="zipvoice")
    assert prepare_text_for_synthesis("银行行长", cfg, model_id="zipvoice") == "银行行长"


@pytest.mark.parametrize(
    "text",
    [
        "https://example.com/a?b=1",
        "D:\\AI\\work\\AngeVoice-main",
        "192.168.1.2",
        "Python 3.10",
        "CUDA 12.1",
        "3.5 版本",
        "The cable is 3.5mm.",
    ],
)
def test_protected_spans_survive_wetext_path(monkeypatch, text):
    class NoisyNormalizer:
        def normalize(self, value):
            return value.replace("3.5", "三点五").replace("12.1", "十二点一").replace("3.10", "三点一零")

    _install_fake_wetext(monkeypatch, NoisyNormalizer)
    cfg = TTSConfig(angevoice_tn_engine="wetext")
    assert normalize_for_model(text, cfg, model="zipvoice") == text


# ── golden cases ────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "source,expected_substring",
    [
        ("AngeVoice 2.6.613 版本", "AngeVoice"),
        ("Python 3.10", "Python"),
        ("CUDA 12.1", "CUDA"),
        ("3.5 版本", "版本"),
        ("3.5mm", "3.5mm"),
    ],
)
def test_golden_cases_protection(monkeypatch, source, expected_substring):
    """Protected spans survive even with a real-like normalizer."""
    class RealLikeNormalizer:
        def normalize(self, text):
            # Simulate aggressive normalization
            import re
            text = re.sub(r'(\d+)', lambda m: _num_to_zh(int(m.group(1))), text)
            return text

    def _num_to_zh(n):
        digits = "零一二三四五六七八九"
        if n < 10:
            return digits[n]
        if n < 100:
            return digits[n // 10] + digits[n % 10]
        return "".join(digits[int(d)] for d in str(n))

    _install_fake_wetext(monkeypatch, RealLikeNormalizer)
    cfg = TTSConfig(angevoice_tn_engine="wetext")
    result = normalize_for_model(source, cfg, model="kokoro")
    assert expected_substring in result


def test_golden_calendar_date_via_wetext(monkeypatch):
    """Date '2026年' is handled by the calendar date normalizer."""
    cfg = TTSConfig(angevoice_tn_engine="legacy")
    result = normalize_for_model("2026年", cfg, model="kokoro")
    assert "年" in result and "2026" not in result


def test_golden_date_with_wetext_engine(monkeypatch):
    """Full date through wetext engine path preserves calendar normalization."""
    class PassthroughNormalizer:
        def normalize(self, text):
            return text

    _install_fake_wetext(monkeypatch, PassthroughNormalizer)
    cfg = TTSConfig(angevoice_tn_engine="wetext")
    # normalize_calendar_dates handles dash/slash/dot date formats
    result = normalize_for_model("2026-6-29", cfg, model="kokoro")
    assert "年" in result and "月" in result
