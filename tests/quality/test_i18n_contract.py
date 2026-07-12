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
DOM_KEY = re.compile(r"data-i18n(?:-template|-placeholder|-title|-aria-label)?=['\"]([^'\"]+)['\"]")
TEMPLATE_DOM_KEY = re.compile(r"data-i18n-template=['\"]([^'\"]+)['\"]")
T_CALL = re.compile(r"(?<![\w$.])t\s*\(")
TEMPLATE_CALL = re.compile(r"(?<![\w$.])renderTranslationTemplate\s*\(")
GROUP_LABEL_KEY = re.compile(r"\blabelKey\s*:\s*['\"]([^'\"]+)['\"]")
pytestmark = pytest.mark.quality
CATALOG_DOMAINS = ("common", "studio", "admin")


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
    "static/common/i18n.js": (
        DynamicKeyAllowance(
            expression="node.dataset.i18nTemplate",
            reason="applyNode renders the statically declared data-i18n-template keys",
            keys=frozenset({"settings.hint"}),
        ),
    ),
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


def _domain_catalog(domain: str, locale: str, locale_root: Path = LOCALE_ROOT) -> dict[str, str]:
    path = locale_root / domain / f"messages.{locale}.js"
    text = path.read_text(encoding="utf-8")
    pairs = [(match.group("key"), match.group("value")) for match in KEY_VALUE.finditer(text)]
    keys = [key for key, _ in pairs]
    assert len(keys) == len(set(keys)), f"Duplicate translation key in {path}"
    return dict(pairs)


def _catalog(locale: str, locale_root: Path = LOCALE_ROOT) -> dict[str, str]:
    merged: dict[str, str] = {}
    for domain in CATALOG_DOMAINS:
        values = _domain_catalog(domain, locale, locale_root)
        overlap = set(merged) & set(values)
        assert not overlap, f"Duplicate {locale} keys across catalog domains: {sorted(overlap)}"
        merged.update(values)
    return merged


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
        catalog_keys = set(_catalog("zh-cn", root / "static" / "locale"))
    if dynamic_allowlist is None:
        dynamic_allowlist = PRODUCTION_DYNAMIC_ALLOWLIST if root.resolve() == PACKAGE_ROOT.resolve() else {}

    referenced: set[str] = set()
    rich_template_keys: set[str] = set()
    errors: list[str] = []
    used_allowances: set[tuple[str, str]] = set()

    for path in sorted((root / "templates").rglob("*.html")):
        source = path.read_text(encoding="utf-8")
        referenced.update(DOM_KEY.findall(source))
        rich_template_keys.update(TEMPLATE_DOM_KEY.findall(source))

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

        for match in TEMPLATE_CALL.finditer(source):
            if re.search(r"(?:export\s+)?function\s+$", source[max(0, match.start() - 40) : match.start()]):
                continue
            _, first_end = _first_argument(source, match.end())
            if first_end >= len(source) or source[first_end] != ",":
                errors.append(f"Malformed rich translation call in {relative}")
                continue
            argument, _ = _first_argument(source, first_end + 1)
            expression = _normalise_expression(argument)
            try:
                value = ast.literal_eval(expression)
            except (SyntaxError, ValueError):
                value = None
            if not isinstance(value, str):
                allowance = allowances.get(expression)
                if allowance is None:
                    errors.append(f"Dynamic rich translation key in {relative}: renderTranslationTemplate(..., {expression})")
                    continue
                proven = frozenset(rich_template_keys) if expression == "node.dataset.i18nTemplate" else frozenset()
                if proven != allowance.keys:
                    errors.append(
                        f"Dynamic-key proof mismatch in {relative}: {expression}; "
                        f"expected {sorted(allowance.keys)}, proved {sorted(proven)}"
                    )
                    continue
                used_allowances.add((relative, expression))
                referenced.update(allowance.keys)
                continue
            referenced.add(value)

    for relative, allowances in dynamic_allowlist.items():
        for allowance in allowances:
            if (relative, allowance.expression) not in used_allowances:
                errors.append(f"Stale dynamic-key allowance in {relative}: {allowance.expression}")

    missing = referenced - catalog_keys
    if missing:
        errors.append(f"Missing translation keys: {sorted(missing)}")
    return I18nScanReport(frozenset(referenced), tuple(errors))


def test_zh_and_en_catalogs_have_identical_keys_and_placeholders() -> None:
    expected_counts = {"common": 15, "studio": 56, "admin": 7}
    for domain, expected in expected_counts.items():
        zh_domain = _domain_catalog(domain, "zh-cn")
        en_domain = _domain_catalog(domain, "en")
        assert len(zh_domain) == len(en_domain) == expected
        assert set(zh_domain) == set(en_domain)
        for key in zh_domain:
            assert PLACEHOLDER.findall(zh_domain[key]) == PLACEHOLDER.findall(en_domain[key]), key
            assert not re.search(r"</?[A-Za-z][^>]*>", zh_domain[key]), key
            assert not re.search(r"</?[A-Za-z][^>]*>", en_domain[key]), key

    zh = _catalog("zh-cn")
    en = _catalog("en")
    assert len(zh) == len(en) == sum(expected_counts.values()) == 78
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
            "common/i18n.js",
            "security_notice.js",
            "app.js",
        ],
        "admin.html": [
            "common/i18n.js",
            "admin.js",
        ],
    }
    for name, ordered in pages.items():
        html = (PACKAGE_ROOT / "templates" / name).read_text(encoding="utf-8")
        assert [html.index(item) for item in ordered] == sorted(html.index(item) for item in ordered)
        assert html.index('type="importmap"') < html.index('type="module"')
        runtime = re.search(r'<script\s+type="module"\s+src="\{\{ asset_url\(\'common/i18n\.js\'\) \}\}"([^>]*)>', html)
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
        r"""^import \{ messages as (\w+Messages) \} from ['"]\.\./locale/(common|studio|admin)/messages\.(zh-cn|en)\.js['"];""",
        runtime_source,
        re.MULTILINE,
    )
    assert imports == [
        ("commonZhCNMessages", "common", "zh-cn"),
        ("commonEnMessages", "common", "en"),
        ("studioZhCNMessages", "studio", "zh-cn"),
        ("studioEnMessages", "studio", "en"),
        ("adminZhCNMessages", "admin", "zh-cn"),
        ("adminEnMessages", "admin", "en"),
    ]
    assert "?h=" not in runtime_source
    assert "data-i18n-html" not in runtime_source
    assert ".innerHTML = translate(" not in runtime_source
    assert "window.AngeVoiceLocales" not in runtime_source
