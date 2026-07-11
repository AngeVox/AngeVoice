"""Hermetic privacy contracts for AngeVoice's local ZipVoice logging patch."""

from __future__ import annotations

import ast
import importlib
import logging
import sys
import types
from pathlib import Path

import pytest


MARKER = "SECRET_TEXT_ANGEVOICE_0B1"
REPO_ROOT = Path(__file__).resolve().parents[1]
TOKENIZER_PATH = REPO_ROOT / "vendor" / "ZipVoice" / "zipvoice" / "tokenizer" / "tokenizer.py"


@pytest.fixture
def tokenizer_module(monkeypatch):
    """Import the vendor tokenizer with only in-memory dependency seams."""

    monkeypatch.syspath_prepend(str(REPO_ROOT / "vendor" / "ZipVoice"))
    monkeypatch.delitem(sys.modules, "zipvoice.tokenizer.tokenizer", raising=False)

    fake_lhotse = types.ModuleType("lhotse")
    fake_lhotse.CutSet = object
    fake_jieba = types.ModuleType("jieba")
    fake_jieba.default_logger = logging.getLogger("fake-jieba")
    fake_pypinyin = types.ModuleType("pypinyin")
    fake_pypinyin.Style = types.SimpleNamespace(TONE3="tone3")
    fake_pypinyin.lazy_pinyin = lambda text, *args, **kwargs: list(text)
    fake_tone_convert = types.ModuleType("pypinyin.contrib.tone_convert")
    fake_tone_convert.to_finals_tone3 = lambda text: text
    fake_tone_convert.to_initials = lambda text: text
    fake_normalizer = types.ModuleType("zipvoice.tokenizer.normalizer")
    fake_normalizer.ChineseTextNormalizer = object
    fake_normalizer.EnglishTextNormalizer = object
    fake_piper = types.ModuleType("piper_phonemize")
    fake_piper.phonemize_espeak = lambda text, _lang: list(text)

    monkeypatch.setitem(sys.modules, "lhotse", fake_lhotse)
    monkeypatch.setitem(sys.modules, "jieba", fake_jieba)
    monkeypatch.setitem(sys.modules, "pypinyin", fake_pypinyin)
    monkeypatch.setitem(sys.modules, "pypinyin.contrib", types.ModuleType("pypinyin.contrib"))
    monkeypatch.setitem(sys.modules, "pypinyin.contrib.tone_convert", fake_tone_convert)
    monkeypatch.setitem(sys.modules, "zipvoice.tokenizer.normalizer", fake_normalizer)
    monkeypatch.setitem(sys.modules, "piper_phonemize", fake_piper)
    return importlib.import_module("zipvoice.tokenizer.tokenizer")


def _instance(cls, **attributes):
    instance = cls.__new__(cls)
    for name, value in attributes.items():
        setattr(instance, name, value)
    return instance


def _assert_marker_absent(records):
    assert records, "the exercised diagnostic must retain a log record"
    for record in records:
        for field in (record.getMessage(), record.msg, repr(record.args), repr(record.exc_info)):
            assert MARKER not in str(field)


@pytest.mark.parametrize(
    ("class_name", "attributes", "message"),
    [
        ("SimpleTokenizer", {"has_tokens": True, "token2id": {}}, "Skipped OOV token in SimpleTokenizer"),
        ("EspeakTokenizer", {"has_tokens": True, "token2id": {}}, "Skipped OOV token in EspeakTokenizer"),
        ("EmiliaTokenizer", {"has_tokens": True, "token2id": {}}, "Skipped OOV token in EmiliaTokenizer"),
        ("LibriTTSTokenizer", {"has_tokens": True, "token2id": {}, "type": "char"}, "Skipped OOV token in LibriTTSTokenizer"),
    ],
)
def test_oov_logging_is_debug_and_never_retains_user_marker(tokenizer_module, caplog, class_name, attributes, message):
    caplog.set_level(logging.DEBUG)
    tokenizer = _instance(getattr(tokenizer_module, class_name), **attributes)

    assert tokenizer.tokens_to_token_ids([[MARKER]]) == [[]]

    records = caplog.records
    assert [record.levelno for record in records] == [logging.DEBUG]
    assert records[0].getMessage() == message
    _assert_marker_absent(records)


def test_malformed_pinyin_warning_never_retains_user_marker(tokenizer_module, caplog):
    caplog.set_level(logging.WARNING)
    tokenizer = _instance(tokenizer_module.EmiliaTokenizer)

    assert tokenizer.tokenize_pinyin(f"<{MARKER}>") == []

    assert [record.levelno for record in caplog.records] == [logging.WARNING]
    assert caplog.records[0].getMessage() == "Skipped malformed pinyin-tag segment"
    _assert_marker_absent(caplog.records)


def test_unsupported_language_warning_never_retains_user_marker(tokenizer_module, monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    tokenizer = _instance(tokenizer_module.EmiliaTokenizer)
    monkeypatch.setattr(tokenizer, "get_segment", lambda _text: [(MARKER, "unsupported")])

    assert tokenizer.texts_to_tokens([MARKER]) == [[]]

    assert [record.levelno for record in caplog.records] == [logging.WARNING]
    assert caplog.records[0].getMessage() == "Skipped segment with unsupported language classification"
    _assert_marker_absent(caplog.records)


def test_espeak_exception_warning_retains_type_not_message(tokenizer_module, monkeypatch, caplog):
    def fail_g2p(*_args):
        raise RuntimeError(MARKER)

    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(tokenizer_module, "phonemize_espeak", fail_g2p)
    tokenizer = _instance(tokenizer_module.EspeakTokenizer, lang="en-us")

    assert tokenizer.g2p(MARKER) == []

    assert [record.levelno for record in caplog.records] == [logging.WARNING]
    assert caplog.records[0].getMessage() == "Espeak tokenization failed (RuntimeError)"
    _assert_marker_absent(caplog.records)


@pytest.mark.parametrize(
    ("method_name", "normalizer_name", "message"),
    [
        ("tokenize_ZH", "chinese_normalizer", "Chinese tokenization failed (RuntimeError)"),
        ("tokenize_EN", "english_normalizer", "English tokenization failed (RuntimeError)"),
    ],
)
def test_language_exception_warnings_retain_type_not_message(tokenizer_module, caplog, method_name, normalizer_name, message):
    def fail_normalize(_text):
        raise RuntimeError(MARKER)

    caplog.set_level(logging.WARNING)
    tokenizer = _instance(tokenizer_module.EmiliaTokenizer, **{normalizer_name: types.SimpleNamespace(normalize=fail_normalize)})

    assert getattr(tokenizer, method_name)(MARKER) == []

    assert [record.levelno for record in caplog.records] == [logging.WARNING]
    assert caplog.records[0].getMessage() == message
    _assert_marker_absent(caplog.records)


def test_pinyin_exception_warning_retains_type_not_message(tokenizer_module, monkeypatch, caplog):
    def fail_separate(_text):
        raise RuntimeError(MARKER)

    caplog.set_level(logging.WARNING)
    tokenizer = _instance(tokenizer_module.EmiliaTokenizer)
    monkeypatch.setattr(tokenizer, "seperate_pinyin", fail_separate)

    assert tokenizer.tokenize_pinyin("<a1>") == []

    assert [record.levelno for record in caplog.records] == [logging.WARNING]
    assert caplog.records[0].getMessage() == "Pinyin tokenization failed (RuntimeError)"
    _assert_marker_absent(caplog.records)


def test_successful_tokenization_paths_emit_no_new_records(tokenizer_module, caplog):
    caplog.set_level(logging.DEBUG)
    simple = _instance(tokenizer_module.SimpleTokenizer, has_tokens=True, token2id={"ok": 1})
    espeak = _instance(tokenizer_module.EspeakTokenizer, has_tokens=True, token2id={"ok": 1})
    emilia = _instance(tokenizer_module.EmiliaTokenizer, has_tokens=True, token2id={"ok": 1})
    libritts = _instance(tokenizer_module.LibriTTSTokenizer, has_tokens=True, token2id={"ok": 1}, type="char")

    assert simple.tokens_to_token_ids([["ok"]]) == [[1]]
    assert espeak.tokens_to_token_ids([["ok"]]) == [[1]]
    assert emilia.tokens_to_token_ids([["ok"]]) == [[1]]
    assert libritts.tokens_to_token_ids([["ok"]]) == [[1]]
    assert not caplog.records


def _is_permitted_exception_type_reference(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "__name__"
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "type"
        and len(node.value.args) == 1
        and isinstance(node.value.args[0], ast.Name)
        and node.value.args[0].id == "ex"
    )


def test_logging_calls_do_not_reference_user_derived_values():
    tree = ast.parse(TOKENIZER_PATH.read_text(encoding="utf-8"))
    forbidden = {"t", "text", "seg", "ex"}

    for call in ast.walk(tree):
        if not (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "logging"
        ):
            continue
        arguments = [*call.args, *(keyword.value for keyword in call.keywords)]
        for argument in arguments:
            if _is_permitted_exception_type_reference(argument):
                continue
            names = {node.id for node in ast.walk(argument) if isinstance(node, ast.Name)}
            assert not (names & forbidden), ast.unparse(call)
