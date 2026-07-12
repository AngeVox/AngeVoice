"""Phase 0 contracts for the lightweight i18n runtime and all UI sources."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import pytest


ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = ROOT / "src" / "kokoro_tts"
LOCALE_ROOT = PACKAGE_ROOT / "static" / "locale"
KEY_VALUE = re.compile(r"^\s*'(?P<key>[^']+)'\s*:\s*'(?P<value>(?:\\'|[^'])*)'\s*,?\s*$", re.MULTILINE)
PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
DOM_KEY = re.compile(r"data-i18n(?:-html|-placeholder|-title)?=['\"]([^'\"]+)['\"]")
T_CALL = re.compile(r"(?<![\w$.])t\s*\(")
GROUP_LABEL_KEY = re.compile(r"\blabelKey\s*:\s*['\"]([^'\"]+)['\"]")
pytestmark = pytest.mark.quality


@dataclass(frozen=True)
class DynamicKeyAllowance:
    expression: str
    reason: str
    keys: frozenset[str]


@dataclass(frozen=True)
class I18nScanReport:
    referenced: frozenset[str]
    errors: tuple[str, ...]


PRODUCTION_DYNAMIC_ALLOWLIST: Mapping[str, tuple[DynamicKeyAllowance, ...]] = {
    "static/app.js": (
        DynamicKeyAllowance(
            expression="group.labelKey",
            reason="renderVoiceTabs iterates the statically declared groups labelKey values",
            keys=frozenset(
                {
                    "voices.all",
                    "voices.female_zh",
                    "voices.male_zh",
                    "voices.en",
                    "voices.favorite",
                    "voices.recent",
                }
            ),
        ),
    ),
    "static/admin.js": (
        DynamicKeyAllowance(
            expression="tab.labelKey",
            reason="renderAdminSubnav translates the statically declared adminSubtabs labelKey values",
            keys=frozenset({"nav.config.text"}),
        ),
    ),
}


def _catalog(name: str, locale_root: Path = LOCALE_ROOT) -> dict[str, str]:
    text = (locale_root / name).read_text(encoding="utf-8")
    pairs = [(match.group("key"), match.group("value")) for match in KEY_VALUE.finditer(text)]
    keys = [key for key, _ in pairs]
    assert len(keys) == len(set(keys)), f"Duplicate translation key in {name}"
    return dict(pairs)


def _normalise_expression(expression: str) -> str:
    return re.sub(r"\s+", " ", expression.strip())


def _first_argument(source: str, start: int) -> tuple[str, int]:
    quote = ""
    escaped = False
    depths = {"(": 0, "[": 0, "{": 0}
    matching = {")": "(", "]": "[", "}": "{"}
    index = start
    while index < len(source):
        char = source[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
        elif char in "'\"`":
            quote = char
        elif char in depths:
            depths[char] += 1
        elif char in matching:
            opener = matching[char]
            if char == ")" and not any(depths.values()):
                return source[start:index], index
            depths[opener] -= 1
        elif char == "," and not any(depths.values()):
            return source[start:index], index
        index += 1
    return source[start:index], index


def _javascript_files(root: Path) -> list[Path]:
    static = root / "static"
    paths = [static / name for name in ("app.js", "admin.js", "security_notice.js")]
    for directory in ("common", "studio", "admin", "docs"):
        base = static / directory
        if base.exists():
            paths.extend(base.rglob("*.js"))
    return sorted(
        {
            path
            for path in paths
            if path.is_file()
            and "vendor" not in {part.lower() for part in path.parts}
            and not path.name.endswith(".min.js")
            and not path.name.startswith("messages.")
        }
    )


def scan_i18n_references(
    root: Path = PACKAGE_ROOT,
    *,
    catalog_keys: set[str] | None = None,
    dynamic_allowlist: Mapping[str, tuple[DynamicKeyAllowance, ...]] | None = None,
) -> I18nScanReport:
    """Scan every supported source path without relying on the JavaScript import graph."""
    root = Path(root)
    if catalog_keys is None:
        catalog_keys = set(_catalog("messages.zh-cn.js", root / "static" / "locale"))
    if dynamic_allowlist is None:
        dynamic_allowlist = PRODUCTION_DYNAMIC_ALLOWLIST if root.resolve() == PACKAGE_ROOT.resolve() else {}

    referenced: set[str] = set()
    errors: list[str] = []
    used_allowances: set[tuple[str, str]] = set()

    for path in sorted((root / "templates").rglob("*.html")):
        referenced.update(DOM_KEY.findall(path.read_text(encoding="utf-8")))

    for path in _javascript_files(root):
        source = path.read_text(encoding="utf-8")
        relative = path.relative_to(root).as_posix()
        allowances = {item.expression: item for item in dynamic_allowlist.get(relative, ())}
        for match in T_CALL.finditer(source):
            if re.search(r"\bfunction\s+$", source[max(0, match.start() - 24) : match.start()]):
                continue
            argument, _ = _first_argument(source, match.end())
            expression = _normalise_expression(argument)
            try:
                value = ast.literal_eval(expression)
            except (SyntaxError, ValueError):
                value = None
            if isinstance(value, str):
                referenced.add(value)
                continue
            allowance = allowances.get(expression)
            if allowance is None:
                errors.append(f"Unallowlisted dynamic translation key in {relative}: t({expression})")
                continue
            if not allowance.reason or not allowance.keys:
                errors.append(f"Invalid dynamic-key allowance in {relative}: {expression}")
                continue
            proven = (
                frozenset(GROUP_LABEL_KEY.findall(source))
                if expression in {"group.labelKey", "tab.labelKey"}
                else frozenset()
            )
            if proven != allowance.keys:
                errors.append(
                    f"Dynamic-key proof mismatch in {relative}: {expression}; "
                    f"expected {sorted(allowance.keys)}, proved {sorted(proven)}"
                )
                continue
            used_allowances.add((relative, expression))
            referenced.update(allowance.keys)

    for relative, allowances in dynamic_allowlist.items():
        for allowance in allowances:
            if (relative, allowance.expression) not in used_allowances:
                errors.append(f"Stale dynamic-key allowance in {relative}: {allowance.expression}")

    missing = referenced - catalog_keys
    if missing:
        errors.append(f"Missing translation keys: {sorted(missing)}")
    return I18nScanReport(frozenset(referenced), tuple(errors))


def test_zh_and_en_catalogs_have_identical_keys_and_placeholders() -> None:
    zh = _catalog("messages.zh-cn.js")
    en = _catalog("messages.en.js")
    assert len(zh) == len(en) == 75
    assert set(zh) == set(en)
    for key in zh:
        assert PLACEHOLDER.findall(zh[key]) == PLACEHOLDER.findall(en[key]), key


def test_current_static_and_javascript_translation_references_exist() -> None:
    report = scan_i18n_references()
    assert report.referenced
    assert not report.errors, "\n".join(report.errors)


def test_pages_load_the_explicit_runtime_before_consumers_without_catalog_tags() -> None:
    pages = {
        "index.html": [
            "/static/common/i18n.js",
            "/static/security_notice.js",
            "/static/app.js",
        ],
        "admin.html": [
            "/static/common/i18n.js",
            "/static/admin.js",
        ],
    }
    for name, ordered in pages.items():
        html = (PACKAGE_ROOT / "templates" / name).read_text(encoding="utf-8")
        assert [html.index(item) for item in ordered] == sorted(html.index(item) for item in ordered)
        runtime = re.search(r'<script\s+type="module"\s+src="/static/common/i18n\.js\?h=[0-9a-f]{12}"([^>]*)>', html)
        assert runtime, name
        assert "async" not in runtime.group(1)
        assert "/static/locale/messages.zh-cn.js" not in html
        assert "/static/locale/messages.en.js" not in html
        assert "/static/locale/translate.js" not in html
    javascript_files = _javascript_files(PACKAGE_ROOT)
    assert PACKAGE_ROOT / "static" / "common" / "i18n.js" in javascript_files
    assert not any(path.name.startswith("messages.") for path in javascript_files)

    runtime_source = (PACKAGE_ROOT / "static" / "common" / "i18n.js").read_text(encoding="utf-8")
    imports = re.findall(
        r"""^import \{ messages as (?:zhCNMessages|enMessages) \} from ['"]\.\./locale/messages\.(?:zh-cn|en)\.js\?h=[0-9a-f]{12}['"];""",
        runtime_source,
        re.MULTILINE,
    )
    assert len(imports) == 2
    assert "window.AngeVoiceLocales" not in runtime_source
