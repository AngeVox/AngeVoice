"""Phase 0 contracts for the lightweight i18n runtime and all UI sources."""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
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
TRANSLATED_PROGRESS_CALL = re.compile(r"(?<![\w$.])setTranslatedProgress\s*\(")
COPY_DESCRIPTOR_CALL = re.compile(r"(?<![\w$.])descriptor\s*\(")
GROUP_LABEL_KEY = re.compile(r"\blabelKey\s*:\s*['\"]([^'\"]+)['\"]")
pytestmark = pytest.mark.quality
CATALOG_DOMAINS = ("common", "studio", "admin")
STUDIO_COPY_DEBT = Path(__file__).with_name("studio_copy_debt.json")
JS_STRING = re.compile(r"(?P<quote>['\"`])(?P<body>(?:\\.|(?!\1).)*?)(?P=quote)")
HAN = re.compile(r"[\u3400-\u9fff]")


@dataclass(frozen=True)
class DynamicKeyAllowance:
    expression: str
    reason: str
    keys: frozenset[str]


@dataclass(frozen=True)
class I18nScanReport:
    referenced: frozenset[str]
    errors: tuple[str, ...]


@dataclass(frozen=True, order=True)
class StudioCopyFinding:
    path: str
    owner: str
    sink: str
    text: str

    def as_dict(self) -> dict[str, str]:
        return {"path": self.path, "owner": self.owner, "sink": self.sink, "text": self.text}


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
        DynamicKeyAllowance(
            expression="copy.key",
            reason="translateDescriptor accepts only literal copy descriptors proven across Studio modules",
            keys=frozenset(
                {
                    "studio.auth.required_admin",
                    "studio.auth.required_file",
                    "studio.model.switching",
                    "studio.model.switched",
                    "studio.model.wake_success",
                    "studio.model.waking",
                    "studio.session.removed",
                    "studio.session.saved",
                    "studio.session.token_required",
                    "studio.record.active",
                    "studio.record.cancelled",
                    "studio.record.complete",
                    "studio.record.complete_at_limit",
                    "studio.record.device_failed",
                    "studio.record.insecure_context",
                    "studio.record.limit_quality_warning",
                    "studio.record.limit_reached",
                    "studio.record.microphone_unavailable",
                    "studio.record.permission_denied",
                    "studio.record.unsupported",
                    "studio.reference_audio.clone",
                    "studio.reference_audio.duration_warning",
                    "studio.reference_audio.media_failed",
                    "studio.reference_audio.preparing",
                    "studio.reference_audio.profile_recording",
                    "studio.reference_audio.saved_failed",
                    "studio.reference_audio.saved_failed_detail",
                    "studio.reference_audio.saved_loading",
                    "studio.reference_audio.saved_ready",
                    "studio.reference_audio.upload_failed",
                    "studio.reference_audio.upload_failed_detail",
                    "studio.reference_audio.upload_ready",
                    "profile.confirm_delete",
                    "profile.delete_failed",
                    "profile.deleted",
                    "profile.name_required",
                    "profile.name_updated",
                    "profile.save_failed",
                    "profile.save_requirements",
                    "profile.saved",
                    "profile.select_saved_first",
                    "profile.update_failed",
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


def _literal_call_keys(source: str, pattern: re.Pattern[str]) -> frozenset[str]:
    keys: set[str] = set()
    for match in pattern.finditer(source):
        if re.search(r"function\s+$", source[max(0, match.start() - 24) : match.start()]):
            continue
        argument, _ = _first_argument(source, match.end())
        try:
            value = ast.literal_eval(_normalise_expression(argument))
        except (SyntaxError, ValueError):
            continue
        if isinstance(value, str):
            keys.add(value)
    return frozenset(keys)


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


def _looks_like_user_copy(value: str) -> bool:
    value = re.sub(r"\s+", " ", value).strip()
    if not value:
        return False
    if HAN.search(value):
        return True
    visible = re.sub(r"\$\{.*?\}", "", value)
    return bool(re.search(r"\b[A-Za-z]{2,}\b[\s,:;.!?]+\b[A-Za-z]{2,}\b", visible))


def _javascript_copy_findings(root: Path) -> set[StudioCopyFinding]:
    findings: set[StudioCopyFinding] = set()
    paths = [root / "static" / "app.js", root / "static" / "security_notice.js"]
    studio = root / "static" / "studio"
    if studio.exists():
        paths.extend(studio.rglob("*.js"))
    for path in sorted(item for item in paths if item.is_file()):
        relative = path.relative_to(root).as_posix()
        owner = "<module>"
        in_error_map = False
        for line in path.read_text(encoding="utf-8").splitlines():
            function = re.match(r"\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(", line)
            if function:
                owner = function.group(1)
            if re.match(r"\s*const\s+USER_ERROR_MESSAGES\s*=\s*\{", line):
                in_error_map = True
                owner = "USER_ERROR_MESSAGES"
            sink = ""
            for needle, name in (
                ("setRecordingStatus(", "recording_status"),
                ("setProgress(", "progress"),
                ("showToast(", "toast"),
                ("setHealth(", "health"),
                ("userFacingErrorMessage(", "error_policy"),
                ("throw new Error(", "error"),
                (".textContent =", "textContent"),
                (".innerHTML =", "innerHTML"),
                (".title =", "title"),
            ):
                if needle in line:
                    sink = name
                    break
            if in_error_map:
                sink = "error_policy"
            if not sink:
                continue
            if "setTranslatedProgress(" in line or re.search(r"\bt\s*\(", line):
                continue
            for match in JS_STRING.finditer(line):
                text = re.sub(r"\s+", " ", match.group("body")).strip()
                if _looks_like_user_copy(text):
                    findings.add(StudioCopyFinding(relative, owner, sink, text))
            if in_error_map and re.match(r"\s*\};", line):
                in_error_map = False
    return findings


class _TemplateCopyScanner(HTMLParser):
    VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self, path: Path, root: Path) -> None:
        super().__init__(convert_charrefs=True)
        self.path = path.relative_to(root).as_posix()
        self.findings: set[StudioCopyFinding] = set()
        self.stack: list[tuple[str, dict[str, str | None]]] = []

    def _localized(self) -> bool:
        return any(
            any(name.startswith("data-i18n") for name in attrs)
            or "data-locale-choice" in attrs
            or "data-current-locale" in attrs
            or attrs.get("aria-hidden") == "true"
            for _, attrs in self.stack
        )

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        mapping = dict(attrs)
        self.stack.append((tag, mapping))
        try:
            if self._localized():
                return
            owner = f"{tag}#{mapping.get('id') or '-'}"
            for name in ("placeholder", "title", "aria-label"):
                value = mapping.get(name)
                if value and _looks_like_user_copy(value):
                    self.findings.add(StudioCopyFinding(self.path, owner, name, re.sub(r"\s+", " ", value).strip()))
        finally:
            if tag in self.VOID_TAGS:
                self.stack.pop()

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID_TAGS:
            self.stack.pop()

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        value = re.sub(r"\s+", " ", data).strip()
        if not value or self._localized() or not _looks_like_user_copy(value):
            return
        tag, attrs = self.stack[-1] if self.stack else ("document", {})
        if tag in {"script", "style"}:
            return
        if tag == "title" and value == "AngeVoice Studio":
            return
        owner = f"{tag}#{attrs.get('id') or '-'}"
        self.findings.add(StudioCopyFinding(self.path, owner, "html_text", value))


def scan_studio_user_copy(root: Path = PACKAGE_ROOT) -> frozenset[StudioCopyFinding]:
    root = Path(root)
    findings = _javascript_copy_findings(root)
    templates = root / "templates"
    if templates.exists():
        for path in sorted(templates.rglob("*.html")):
            if path.name != "index.html":
                continue
            scanner = _TemplateCopyScanner(path, root)
            scanner.feed(path.read_text(encoding="utf-8"))
            findings.update(scanner.findings)
    return frozenset(findings)


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
    javascript_files = _javascript_files(root)
    descriptor_keys = frozenset().union(
        *(
            _literal_call_keys(path.read_text(encoding="utf-8"), pattern)
            for path in javascript_files
            for pattern in (TRANSLATED_PROGRESS_CALL, COPY_DESCRIPTOR_CALL)
        )
    )

    for path in sorted((root / "templates").rglob("*.html")):
        source = path.read_text(encoding="utf-8")
        referenced.update(DOM_KEY.findall(source))
        rich_template_keys.update(TEMPLATE_DOM_KEY.findall(source))

    for path in javascript_files:
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
                else descriptor_keys
                if expression == "copy.key"
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

        for pattern, call_name in (
            (TRANSLATED_PROGRESS_CALL, "setTranslatedProgress"),
            (COPY_DESCRIPTOR_CALL, "descriptor"),
        ):
            for match in pattern.finditer(source):
                if re.search(r"function\s+$", source[max(0, match.start() - 24) : match.start()]):
                    continue
                argument, _ = _first_argument(source, match.end())
                expression = _normalise_expression(argument)
                try:
                    value = ast.literal_eval(expression)
                except (SyntaxError, ValueError):
                    value = None
                if not isinstance(value, str):
                    errors.append(f"Dynamic copy key in {relative}: {call_name}({expression})")
                    continue
                referenced.add(value)

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
    expected_counts = {"common": 15, "studio": 149, "admin": 7}
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
    assert len(zh) == len(en) == sum(expected_counts.values()) == 171
    assert set(zh) == set(en)
    for key in zh:
        assert PLACEHOLDER.findall(zh[key]) == PLACEHOLDER.findall(en[key]), key


def test_english_settings_template_owns_spacing_before_the_session_notice() -> None:
    english = _catalog("en")
    assert english["settings.session_notice"] == english["settings.session_notice"].lstrip()
    assert "{admin}. {session}" in english["settings.hint"]


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


def test_studio_hardcoded_user_copy_matches_the_classified_shrinking_debt_registry() -> None:
    registered = json.loads(STUDIO_COPY_DEBT.read_text(encoding="utf-8"))
    assert isinstance(registered, list)
    fingerprints = []
    for item in registered:
        assert set(item) == {"path", "owner", "sink", "text", "classification", "target_phase", "reason"}
        assert item["classification"] in {"lifecycle_high_risk", "error_policy_defer_1H"}
        assert item["target_phase"] in {"1E-3A", "1E-3B", "1E-3C", "1H"}
        assert item["reason"].strip()
        fingerprints.append({key: item[key] for key in ("path", "owner", "sink", "text")})
    assert len(fingerprints) == len({tuple(item.values()) for item in fingerprints})
    actual = {
        (finding.path, finding.owner, finding.sink, finding.text)
        for finding in scan_studio_user_copy()
    }
    expected = {tuple(item.values()) for item in fingerprints}
    assert actual == expected


def test_studio_copy_scanner_finds_natural_language_in_unimported_nested_module(tmp_path: Path) -> None:
    root = tmp_path
    nested = root / "static" / "studio" / "nested"
    nested.mkdir(parents=True)
    (root / "templates").mkdir()
    (nested / "future.js").write_text(
        "function render() { setProgress('Visible English sentence'); }",
        encoding="utf-8",
    )
    findings = scan_studio_user_copy(root)
    assert StudioCopyFinding(
        "static/studio/nested/future.js",
        "render",
        "progress",
        "Visible English sentence",
    ) in findings


def test_studio_copy_scanner_finds_template_text_and_skips_catalogued_fallback(tmp_path: Path) -> None:
    root = tmp_path
    (root / "static" / "studio").mkdir(parents=True)
    templates = root / "templates"
    templates.mkdir()
    (templates / "index.html").write_text(
        '<p>Visible English sentence</p>'
        '<p data-i18n="known.key">Catalogued fallback sentence</p>'
        '<input placeholder="Visible input guidance">',
        encoding="utf-8",
    )
    findings = scan_studio_user_copy(root)
    assert StudioCopyFinding("templates/index.html", "p#-", "html_text", "Visible English sentence") in findings
    assert StudioCopyFinding("templates/index.html", "input#-", "placeholder", "Visible input guidance") in findings
    assert not any(finding.text == "Catalogued fallback sentence" for finding in findings)


def test_translated_progress_keys_are_literal_and_proven_by_the_scanner(tmp_path: Path) -> None:
    root = tmp_path
    nested = root / "static" / "studio"
    nested.mkdir(parents=True)
    (root / "templates").mkdir()
    (nested / "future.js").write_text(
        "function run() { setTranslatedProgress(dynamicKey); }",
        encoding="utf-8",
    )
    report = scan_i18n_references(root, catalog_keys=set())
    assert any("Dynamic copy key" in error and "setTranslatedProgress(dynamicKey)" in error for error in report.errors)
