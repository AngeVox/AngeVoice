"""Phase 0 contracts for the existing lightweight i18n runtime."""

from __future__ import annotations

import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = ROOT / "src" / "kokoro_tts"
LOCALE_ROOT = PACKAGE_ROOT / "static" / "locale"
KEY_VALUE = re.compile(r"^\s*'(?P<key>[^']+)'\s*:\s*'(?P<value>(?:\\'|[^'])*)'\s*,?\s*$", re.MULTILINE)
PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
DOM_KEY = re.compile(r"data-i18n(?:-html|-placeholder|-title)?=['\"]([^'\"]+)['\"]")
JS_T_KEY = re.compile(r"\bt\(\s*['\"]([^'\"]+)['\"]")
pytestmark = pytest.mark.quality


def _catalog(name: str) -> dict[str, str]:
    text = (LOCALE_ROOT / name).read_text(encoding="utf-8")
    pairs = [(match.group("key"), match.group("value")) for match in KEY_VALUE.finditer(text)]
    keys = [key for key, _ in pairs]
    assert len(keys) == len(set(keys)), f"Duplicate translation key in {name}"
    return dict(pairs)


def test_zh_and_en_catalogs_have_identical_keys_and_placeholders() -> None:
    zh = _catalog("messages.zh-cn.js")
    en = _catalog("messages.en.js")
    assert zh
    assert set(zh) == set(en)
    for key in zh:
        assert PLACEHOLDER.findall(zh[key]) == PLACEHOLDER.findall(en[key]), key


def test_current_static_and_javascript_translation_references_exist() -> None:
    keys = set(_catalog("messages.zh-cn.js"))
    referenced: set[str] = set()
    for path in (PACKAGE_ROOT / "templates").glob("*.html"):
        referenced.update(DOM_KEY.findall(path.read_text(encoding="utf-8")))
    for name in ("app.js", "admin.js", "security_notice.js"):
        referenced.update(JS_T_KEY.findall((PACKAGE_ROOT / "static" / name).read_text(encoding="utf-8")))
    assert referenced
    assert not (referenced - keys), f"Missing translation keys: {sorted(referenced - keys)}"


def test_studio_loads_both_catalogs_before_the_runtime() -> None:
    html = (PACKAGE_ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    zh_index = html.index("/static/locale/messages.zh-cn.js")
    en_index = html.index("/static/locale/messages.en.js")
    runtime_index = html.index("/static/locale/translate.js")
    assert zh_index < runtime_index
    assert en_index < runtime_index
