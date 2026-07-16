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
ADMIN_COPY_DEBT = Path(__file__).with_name("admin_copy_debt.json")
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


@dataclass(frozen=True, order=True)
class AdminCopyFinding:
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
                    "studio.compose.text_required",
                    "studio.error.api_key_invalid",
                    "studio.error.api_key_rotated",
                    "studio.error.ffmpeg_conversion_failed",
                    "studio.error.ffmpeg_disabled",
                    "studio.error.ffmpeg_unavailable",
                    "studio.error.generation_failed",
                    "studio.error.model_switch_failed",
                    "studio.error.model_wake_failed",
                    "studio.error.no_synthesizable_text",
                    "studio.error.reference_audio_read_failed",
                    "studio.error.request_failed",
                    "studio.error.session_expired",
                    "studio.error.session_save_failed",
                    "studio.error.session_save_failed_status",
                    "studio.error.stream_playback_failed",
                    "studio.error.stream_synthesis_failed",
                    "studio.error.synthesis_safe_fallback",
                    "studio.error.websocket_failed",
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
                    "studio.synthesis.http.completed",
                    "studio.synthesis.http.generating",
                    "studio.synthesis.http.generating_conditioned",
                    "studio.synthesis.http.prompt_text_required",
                    "studio.synthesis.http.reference_required",
                    "studio.synthesis.stopped",
                    "profile.confirm_delete",
                    "profile.delete_failed",
                    "profile.delete_missing",
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
            keys=frozenset(
                {
                    "subnav.config.runtime",
                    "subnav.config.quality",
                    "nav.config.text",
                    "subnav.security.auth",
                    "subnav.security.deploy",
                    "subnav.api.diagnostics",
                    "subnav.api.raw",
                }
            ),
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
    return len(re.findall(r"[A-Za-z]{2,}", visible)) >= 2


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
            if in_error_map and "descriptor(" in line:
                continue
            if "setTranslatedProgress(" in line or re.search(r"\bt\s*\(", line):
                continue
            for match in JS_STRING.finditer(line):
                text = re.sub(r"\s+", " ", match.group("body")).strip()
                if _studio_is_technical_literal(text):
                    continue
                if _looks_like_user_copy(text):
                    findings.add(StudioCopyFinding(relative, owner, sink, text))
            if in_error_map and re.match(r"\s*\};", line):
                in_error_map = False
    return findings


def _studio_is_technical_literal(value: str) -> bool:
    return bool(
        re.fullmatch(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+", value)
        or value.startswith((".", "#", "["))
        or re.fullmatch(r"[A-Z][A-Z0-9_]+", value)
    )


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

    def _is_technical_copy(self, value: str) -> bool:
        return bool(re.fullmatch(r"[A-Z][A-Z0-9_]+", value))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        mapping = dict(attrs)
        self.stack.append((tag, mapping))
        try:
            if self._localized():
                return
            owner = f"{tag}#{mapping.get('id') or '-'}"
            for name in ("placeholder", "title", "aria-label"):
                value = mapping.get(name)
                if value and not self._is_technical_copy(value) and _looks_like_user_copy(value):
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
        if not value or self._localized() or self._is_technical_copy(value) or not _looks_like_user_copy(value):
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


class _AdminMarkupText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.fragments: list[str] = []

    def handle_data(self, data: str) -> None:
        value = re.sub(r"\s+", " ", data).strip()
        if value:
            self.fragments.append(value)


def _strip_template_interpolations(value: str) -> str:
    result: list[str] = []
    index = 0
    while index < len(value):
        if value.startswith("${", index):
            depth = 1
            index += 2
            while index < len(value) and depth:
                if value[index] == "{":
                    depth += 1
                elif value[index] == "}":
                    depth -= 1
                index += 1
            continue
        result.append(value[index])
        index += 1
    return "".join(result)


def _admin_visible_copy_fragments(value: str) -> tuple[str, ...]:
    if not re.search(r"</?[A-Za-z][^>]*>", value):
        return (value,)
    parser = _AdminMarkupText()
    parser.feed(value)
    return tuple(fragment for item in parser.fragments if (fragment := _strip_template_interpolations(item).strip()))


@dataclass(frozen=True)
class _AdminJavaScriptLiteral:
    start: int
    end: int
    body: str


def _iter_admin_javascript_literals(source: str) -> list[_AdminJavaScriptLiteral]:
    literals: list[_AdminJavaScriptLiteral] = []
    index = 0
    while index < len(source):
        if source.startswith("//", index):
            newline = source.find("\n", index)
            index = len(source) if newline < 0 else newline + 1
            continue
        if source.startswith("/*", index):
            end_comment = source.find("*/", index + 2)
            index = len(source) if end_comment < 0 else end_comment + 2
            continue
        quote = source[index]
        if quote not in "'\"`":
            index += 1
            continue
        start = index
        index += 1
        body_start = index
        escaped = False
        while index < len(source):
            char = source[index]
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                literals.append(_AdminJavaScriptLiteral(start, index + 1, source[body_start:index]))
                index += 1
                break
            index += 1
        else:
            break
    return literals


def _admin_literal_context(source: str, start: int) -> str:
    prefix = source[max(0, start - 320) : start]
    if re.search(r"\bt\s*\(\s*$", prefix):
        return "translation_key"
    if re.search(r"\.setAttribute\s*\(\s*['\"](?:title|placeholder|aria-label)['\"]\s*,\s*$", prefix):
        return "visible_attribute"
    if re.search(r"\.setAttribute\s*\(\s*['\"](?:class|data-[a-z0-9-]+)['\"]\s*,\s*$", prefix):
        return "technical_argument"
    if re.search(r"\.setAttribute\s*\(\s*$", prefix):
        return "technical_argument"
    if re.search(r"(?:classList\.(?:add|remove|toggle|contains)|querySelector(?:All)?|closest|getElementById|\$|addEventListener|removeEventListener|api|fetch)\s*\(\s*$", prefix):
        return "technical_argument"
    if re.search(r"\btoast\s*\(\s*$", prefix):
        return "toast"
    if re.search(r"\bconfirm\s*\(\s*$", prefix):
        return "confirm"
    if re.search(r"\bsetCredentialFeedback\s*\(\s*['\"`].*?['\"`]\s*,\s*$", prefix):
        return "technical_argument"
    if re.search(r"\bsetCredentialFeedback\s*\(\s*$", prefix):
        return "credential_feedback"
    if re.search(r"\.textContent\s*=\s*$", prefix):
        return "textContent"
    for property_name, sink in (
        ("innerHTML", "innerHTML"),
        ("title", "title"),
        ("placeholder", "placeholder"),
        ("ariaLabel", "ariaLabel"),
    ):
        if re.search(rf"\.{property_name}\s*=\s*$", prefix):
            return sink
    return "module_literal"


def _admin_literal_sink(source: str, start: int, context: str) -> str:
    if context != "module_literal":
        return context
    statement = source[max(source.rfind(";", 0, start), source.rfind("\n", 0, start)) + 1 : start]
    if re.search(r"\btoast\s*\(", statement):
        return "toast"
    if re.search(r"\bconfirm\s*\(", statement):
        return "confirm"
    if re.search(r"\bsetCredentialFeedback\s*\(", statement):
        return "credential_feedback"
    if re.search(r"\.textContent\s*=", statement):
        return "textContent"
    return "module_literal"


def _admin_is_technical_literal(context: str, value: str) -> bool:
    without_interpolation = re.sub(r"\$\{[^{}]*\}", "", value).strip()
    if context in {"translation_key", "technical_argument"}:
        return True
    if re.fullmatch(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+", value):
        return True
    if re.fullmatch(r"[a-z][a-z0-9_-]*:[a-z][a-z0-9_-]*", value):
        return True
    if re.fullmatch(r"[a-z0-9_.-]+\.(?:css|html|js|json|zip)", value, re.IGNORECASE):
        return True
    if value in {"CPU ONNX INT8", "Content-Type"}:
        return True
    if re.fullmatch(r"[a-z0-9.+-]+/[a-z0-9.+-]+", value, re.IGNORECASE):
        return True
    if value.startswith(("./", "/", ":")):
        return True
    if re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)+", value):
        return True
    if "${" in value and re.fullmatch(r"[a-z][a-z0-9-]*", without_interpolation):
        return True
    if value.startswith("${") and "copy." in value and not HAN.search(value):
        return True
    if re.fullmatch(r"data-[a-z0-9-]+=[\"'][^\"']*[\"']", value):
        return True
    return without_interpolation in {""}


ADMIN_VISIBLE_SINKS = frozenset(
    {
        "toast",
        "confirm",
        "credential_feedback",
        "textContent",
        "innerHTML",
        "title",
        "placeholder",
        "aria-label",
        "ariaLabel",
        "visible_attribute",
        "html_text",
    }
)


def _admin_visible_sink_has_copy(value: str, sink: str) -> bool:
    return bool(HAN.search(value)) or _looks_like_user_copy(value) or (
        sink in ADMIN_VISIBLE_SINKS and bool(re.search(r"[A-Za-z]{2,}", value))
    )


def _admin_javascript_copy_findings(root: Path) -> set[AdminCopyFinding]:
    static = root / "static"
    paths = [static / "admin.js"]
    admin_modules = static / "admin"
    if admin_modules.exists():
        paths.extend(admin_modules.rglob("*.js"))
    findings: set[AdminCopyFinding] = set()
    for path in sorted(item for item in paths if item.is_file()):
        relative = path.relative_to(root).as_posix()
        source = path.read_text(encoding="utf-8")
        owner = "<module>"
        owners: list[str] = []
        for line in source.splitlines():
            function = re.match(r"\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(", line)
            if function:
                owner = function.group(1)
            click_handler = re.match(r"\s*\$\('([^']+)'\)\.onclick", line)
            if click_handler:
                owner = f"onclick:{click_handler.group(1)}"
            elif "document.addEventListener('click'" in line:
                owner = "document.click"
            owners.append(owner)
        for literal in _iter_admin_javascript_literals(source):
            text = re.sub(r"\s+", " ", literal.body).strip()
            context = _admin_literal_context(source, literal.start)
            if _admin_is_technical_literal(context, text):
                continue
            line_number = source.count("\n", 0, literal.start)
            literal_owner = owners[line_number]
            sink = _admin_literal_sink(source, literal.start, context)
            if context == "module_literal" and (
                "currentAdminPresentationCopy" in literal_owner
                or re.match(r"\s*(load|switch|unload|forceStop|checkAssets|repairAssets):", source[source.rfind("\n", 0, literal.start) + 1 : literal.start])
            ):
                sink = "presentation_action"
            for visible in _admin_visible_copy_fragments(text):
                if _admin_visible_sink_has_copy(visible, sink):
                    findings.add(AdminCopyFinding(relative, literal_owner, sink, visible))
    return findings


class _AdminTemplateCopyScanner(_TemplateCopyScanner):
    DYNAMIC_IDS = {
        "admin-health-pill",
        "runtime-config-note",
        "update-message",
        "api-key-status",
        "default-admin-warning",
        "admin-credentials-feedback",
        "admin-toast",
        "admin-json",
    }
    TECHNICAL_COPY = {
        "AngeVoice Admin",
        "AngeVoice Studio",
        "Ange",
        "Voice",
        "Studio",
        "Admin",
        "API",
        "ENV",
        "JSON",
        "ENV Patch",
        "Raw State",
        "PBKDF2",
        "Kokoro",
        "MOSS",
        "ZipVoice",
        "admin",
        "admin123",
    }

    def _localized(self) -> bool:
        return super()._localized() or any(attrs.get("id") in self.DYNAMIC_IDS for _, attrs in self.stack)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        mapping = dict(attrs)
        self.stack.append((tag, mapping))
        try:
            if self._localized():
                return
            owner = f"{tag}#{mapping.get('id') or '-'}"
            for name in ("placeholder", "title", "aria-label"):
                value = mapping.get(name)
                sink = name
                if value and value not in self.TECHNICAL_COPY and _admin_visible_sink_has_copy(value, sink):
                    self.findings.add(AdminCopyFinding(self.path, owner, sink, re.sub(r"\s+", " ", value).strip()))
        finally:
            if tag in self.VOID_TAGS:
                self.stack.pop()

    def handle_data(self, data: str) -> None:
        value = re.sub(r"\s+", " ", data).strip()
        if not value or self._localized() or value in self.TECHNICAL_COPY or not _admin_visible_sink_has_copy(value, "html_text"):
            return
        tag, attrs = self.stack[-1] if self.stack else ("document", {})
        if tag not in {"script", "style"}:
            self.findings.add(AdminCopyFinding(self.path, f"{tag}#{attrs.get('id') or '-'}", "html_text", value))


def scan_admin_user_copy(root: Path = PACKAGE_ROOT) -> frozenset[AdminCopyFinding]:
    root = Path(root)
    findings = _admin_javascript_copy_findings(root)
    template = root / "templates" / "admin.html"
    if template.exists():
        scanner = _AdminTemplateCopyScanner(template, root)
        scanner.feed(template.read_text(encoding="utf-8"))
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


def scan_admin_catalog_references(root: Path = PACKAGE_ROOT) -> I18nScanReport:
    """Prove Admin keys are owned by Admin production sources, not other pages."""
    root = Path(root)
    static = root / "static"
    paths = [static / "admin.js"]
    admin_modules = static / "admin"
    if admin_modules.exists():
        paths.extend(admin_modules.rglob("*.js"))

    referenced: set[str] = set()
    errors: list[str] = []
    template = root / "templates" / "admin.html"
    if template.exists():
        source = template.read_text(encoding="utf-8")
        referenced.update(DOM_KEY.findall(source))

    for path in sorted(item for item in paths if item.is_file()):
        source = path.read_text(encoding="utf-8")
        relative = path.relative_to(root).as_posix()
        for match in T_CALL.finditer(source):
            argument, _ = _first_argument(source, match.end())
            expression = _normalise_expression(argument)
            try:
                value = ast.literal_eval(expression)
            except (SyntaxError, ValueError):
                value = None
            if isinstance(value, str):
                referenced.add(value)
            elif relative == "static/admin.js" and expression == "tab.labelKey":
                allowance = PRODUCTION_DYNAMIC_ALLOWLIST[relative][0]
                proven = frozenset(GROUP_LABEL_KEY.findall(source))
                if proven != allowance.keys:
                    errors.append(
                        f"Admin dynamic-key proof mismatch: expected {sorted(allowance.keys)}, proved {sorted(proven)}"
                    )
                else:
                    referenced.update(allowance.keys)
            else:
                errors.append(f"Unallowlisted Admin dynamic translation key in {relative}: t({expression})")

        for match in TEMPLATE_CALL.finditer(source):
            _, first_end = _first_argument(source, match.end())
            if first_end >= len(source) or source[first_end] != ",":
                errors.append(f"Malformed Admin rich translation call in {relative}")
                continue
            argument, _ = _first_argument(source, first_end + 1)
            try:
                value = ast.literal_eval(_normalise_expression(argument))
            except (SyntaxError, ValueError):
                value = None
            if isinstance(value, str):
                referenced.add(value)
            else:
                errors.append(f"Dynamic Admin rich translation key in {relative}")

    return I18nScanReport(frozenset(referenced), tuple(errors))


def test_zh_and_en_catalogs_have_identical_keys_and_placeholders() -> None:
    expected_counts = {"common": 15, "studio": 187, "admin": 114}
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
    assert len(zh) == len(en) == sum(expected_counts.values()) == 316
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


def test_admin_catalog_keys_are_all_referenced_by_admin_production_sources() -> None:
    report = scan_admin_catalog_references()
    admin_keys = set(_domain_catalog("admin", "zh-cn"))
    assert {"nav.config.text", "section.dictionary.title"} <= report.referenced
    assert not report.errors, "\n".join(report.errors)
    assert admin_keys <= report.referenced


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
    assert registered == []
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


def test_admin_hardcoded_user_copy_matches_the_independent_b2_b3_debt_registry() -> None:
    registered = json.loads(ADMIN_COPY_DEBT.read_text(encoding="utf-8"))
    fingerprints = []
    for item in registered:
        assert set(item) == {"path", "owner", "sink", "text", "classification", "target_phase", "reason"}
        assert item["classification"] == "action_or_transient"
        assert item["target_phase"] in {"P1-4B2", "P1-4B3"}
        assert item["reason"].strip()
        fingerprints.append({key: item[key] for key in ("path", "owner", "sink", "text")})
    assert fingerprints == sorted(fingerprints, key=lambda item: tuple(item.values()))
    assert len(fingerprints) == len({tuple(item.values()) for item in fingerprints})
    actual = {
        (finding.path, finding.owner, finding.sink, finding.text)
        for finding in scan_admin_user_copy()
    }
    expected = {tuple(item.values()) for item in fingerprints}
    assert actual == expected


def test_admin_copy_scanner_finds_unregistered_nested_module_and_template_copy(tmp_path: Path) -> None:
    root = tmp_path
    nested = root / "static" / "admin" / "future"
    nested.mkdir(parents=True)
    (root / "templates").mkdir()
    (nested / "copy.js").write_text("function render() { toast('新增可见文案'); }", encoding="utf-8")
    (root / "templates" / "admin.html").write_text('<p>新增模板文案</p>', encoding="utf-8")
    findings = scan_admin_user_copy(root)
    assert AdminCopyFinding("static/admin/future/copy.js", "render", "toast", "新增可见文案") in findings
    assert AdminCopyFinding("templates/admin.html", "p#-", "html_text", "新增模板文案") in findings


def test_admin_copy_scanner_finds_english_user_copy(tmp_path: Path) -> None:
    root = tmp_path
    (root / "static").mkdir()
    (root / "templates").mkdir()
    (root / "static" / "admin.js").write_text(
        "function render() { toast('New visible message'); }",
        encoding="utf-8",
    )
    findings = scan_admin_user_copy(root)
    assert AdminCopyFinding("static/admin.js", "render", "toast", "New visible message") in findings


def test_admin_copy_scanner_does_not_skip_mixed_translated_and_literal_copy(tmp_path: Path) -> None:
    root = tmp_path
    (root / "static").mkdir()
    (root / "templates").mkdir()
    (root / "static" / "admin.js").write_text(
        "function render() {\n"
        "  toast(t('known.key') + ' New visible message');\n"
        "  toast(`${t('known.key')} 新增可见文案`);\n"
        "}",
        encoding="utf-8",
    )
    findings = scan_admin_user_copy(root)
    assert AdminCopyFinding("static/admin.js", "render", "toast", "New visible message") in findings
    assert AdminCopyFinding("static/admin.js", "render", "toast", "${t('known.key')} 新增可见文案") in findings
    assert not any(finding.text == "known.key" for finding in findings)


def test_admin_copy_scanner_finds_user_copy_inside_html_markup(tmp_path: Path) -> None:
    root = tmp_path
    (root / "static").mkdir()
    (root / "templates").mkdir()
    (root / "static" / "admin.js").write_text(
        "function render() { panel.innerHTML = '<span>New visible message</span>'; }",
        encoding="utf-8",
    )
    findings = scan_admin_user_copy(root)
    assert AdminCopyFinding("static/admin.js", "render", "innerHTML", "New visible message") in findings


def test_admin_copy_scanner_does_not_hide_comparison_copy(tmp_path: Path) -> None:
    root = tmp_path
    (root / "static").mkdir()
    (root / "templates").mkdir()
    (root / "static" / "admin.js").write_text(
        "function render() {\n"
        "  toast('Value must be > 0');\n"
        "  toast('Use a value < 10');\n"
        "}",
        encoding="utf-8",
    )
    findings = scan_admin_user_copy(root)
    assert AdminCopyFinding("static/admin.js", "render", "toast", "Value must be > 0") in findings
    assert AdminCopyFinding("static/admin.js", "render", "toast", "Use a value < 10") in findings


def test_admin_copy_scanner_does_not_hide_hyphenated_english_copy(tmp_path: Path) -> None:
    root = tmp_path
    (root / "static").mkdir()
    (root / "templates").mkdir()
    (root / "static" / "admin.js").write_text(
        "function render() {\n"
        "  toast('low-vram protection enabled');\n"
        "  toast('model-load failed');\n"
        "}",
        encoding="utf-8",
    )
    findings = scan_admin_user_copy(root)
    assert AdminCopyFinding("static/admin.js", "render", "toast", "low-vram protection enabled") in findings
    assert AdminCopyFinding("static/admin.js", "render", "toast", "model-load failed") in findings


def test_admin_copy_scanner_skips_structural_technical_literals(tmp_path: Path) -> None:
    root = tmp_path
    (root / "static").mkdir()
    (root / "templates").mkdir()
    (root / "static" / "admin.js").write_text(
        "function render() {\n"
        "  panel.innerHTML = '<span class=\"status-pill\"></span>';\n"
        "  element.classList.add('hidden-panel');\n"
        "  document.querySelector('.admin-panel');\n"
        "  api('/admin/api/status');\n"
        "  document.addEventListener('angevoice:locale-changed', handler);\n"
        "  const file = 'messages.en.js';\n"
        "}",
        encoding="utf-8",
    )
    assert not scan_admin_user_copy(root)


def test_admin_copy_scanner_filters_only_the_current_selector_literal(tmp_path: Path) -> None:
    root = tmp_path
    (root / "static").mkdir()
    (root / "templates").mkdir()
    (root / "static" / "admin.js").write_text(
        "document.querySelector('#status').textContent = 'New visible message';",
        encoding="utf-8",
    )
    findings = scan_admin_user_copy(root)
    assert AdminCopyFinding("static/admin.js", "<module>", "textContent", "New visible message") in findings
    assert not any(finding.text == "#status" for finding in findings)


def test_admin_copy_scanner_does_not_hide_toast_after_api_literal(tmp_path: Path) -> None:
    root = tmp_path
    (root / "static").mkdir()
    (root / "templates").mkdir()
    (root / "static" / "admin.js").write_text(
        "api('/admin/api/status').catch(() => toast('Failed to load model'));",
        encoding="utf-8",
    )
    findings = scan_admin_user_copy(root)
    assert AdminCopyFinding("static/admin.js", "<module>", "toast", "Failed to load model") in findings
    assert not any(finding.text == "/admin/api/status" for finding in findings)


def test_admin_copy_scanner_does_not_hide_toast_after_class_token(tmp_path: Path) -> None:
    root = tmp_path
    (root / "static").mkdir()
    (root / "templates").mkdir()
    (root / "static" / "admin.js").write_text(
        "element.classList.add('busy'); toast('New visible message');",
        encoding="utf-8",
    )
    findings = scan_admin_user_copy(root)
    assert AdminCopyFinding("static/admin.js", "<module>", "toast", "New visible message") in findings
    assert not any(finding.text == "busy" for finding in findings)


def test_admin_copy_scanner_does_not_hide_toast_after_event_name(tmp_path: Path) -> None:
    root = tmp_path
    (root / "static").mkdir()
    (root / "templates").mkdir()
    (root / "static" / "admin.js").write_text(
        "document.addEventListener('click', () => toast('Action completed'));",
        encoding="utf-8",
    )
    findings = scan_admin_user_copy(root)
    assert AdminCopyFinding("static/admin.js", "document.click", "toast", "Action completed") in findings
    assert not any(finding.text == "click" for finding in findings)


def test_admin_copy_scanner_keeps_visible_bracketed_and_hyphenated_copy(tmp_path: Path) -> None:
    root = tmp_path
    (root / "static").mkdir()
    (root / "templates").mkdir()
    (root / "static" / "admin.js").write_text(
        "toast('[Warning] Update available');\n"
        "toast('low-vram');\n"
        "toast('model-load');\n"
        "toast('CPU fallback');\n"
        "element.classList.add('low-vram');\n"
        "document.querySelector('[data-state]');",
        encoding="utf-8",
    )
    findings = scan_admin_user_copy(root)
    for text in ("[Warning] Update available", "low-vram", "model-load", "CPU fallback"):
        assert AdminCopyFinding("static/admin.js", "<module>", "toast", text) in findings
    assert not any(finding.text in {"[data-state]"} for finding in findings)


def test_admin_copy_scanner_finds_visible_copy_in_multiline_template(tmp_path: Path) -> None:
    root = tmp_path
    (root / "static").mkdir()
    (root / "templates").mkdir()
    (root / "static" / "admin.js").write_text(
        "function render() {\n"
        "  panel.innerHTML = `\n"
        "    <article class=\"card\">\n"
        "      <span>New visible message</span>\n"
        "    </article>\n"
        "  `;\n"
        "}",
        encoding="utf-8",
    )
    assert scan_admin_user_copy(root) == frozenset(
        {AdminCopyFinding("static/admin.js", "render", "innerHTML", "New visible message")}
    )


def test_admin_copy_scanner_skips_markup_and_dynamic_copy_in_multiline_template(tmp_path: Path) -> None:
    root = tmp_path
    (root / "static").mkdir()
    (root / "templates").mkdir()
    (root / "static" / "admin.js").write_text(
        "function render() {\n"
        "  return `\n"
        "    <article class=\"card\">\n"
        "      <span>${copy.status}</span>\n"
        "    </article>\n"
        "  `;\n"
        "}",
        encoding="utf-8",
    )
    assert not scan_admin_user_copy(root)


def test_admin_copy_scanner_finds_single_word_toast_and_confirm_copy(tmp_path: Path) -> None:
    root = tmp_path
    (root / "static").mkdir()
    (root / "templates").mkdir()
    (root / "static" / "admin.js").write_text(
        "toast('Failed');\nconfirm('Proceed?');",
        encoding="utf-8",
    )
    findings = scan_admin_user_copy(root)
    assert AdminCopyFinding("static/admin.js", "<module>", "toast", "Failed") in findings
    assert AdminCopyFinding("static/admin.js", "<module>", "confirm", "Proceed?") in findings


def test_admin_copy_scanner_finds_single_word_dom_property_copy(tmp_path: Path) -> None:
    root = tmp_path
    (root / "static").mkdir()
    (root / "templates").mkdir()
    (root / "static" / "admin.js").write_text(
        "status.textContent = 'Loading';\n"
        "status.innerHTML = '<span>Loading</span>';\n"
        "button.title = 'Refresh';\n"
        "input.placeholder = 'Username';\n"
        "button.ariaLabel = 'Refresh';",
        encoding="utf-8",
    )
    findings = scan_admin_user_copy(root)
    for sink, text in (
        ("textContent", "Loading"),
        ("innerHTML", "Loading"),
        ("title", "Refresh"),
        ("placeholder", "Username"),
        ("ariaLabel", "Refresh"),
    ):
        assert AdminCopyFinding("static/admin.js", "<module>", sink, text) in findings


def test_admin_copy_scanner_finds_visible_attribute_copy(tmp_path: Path) -> None:
    root = tmp_path
    (root / "static").mkdir()
    (root / "templates").mkdir()
    (root / "static" / "admin.js").write_text(
        "node.setAttribute('title', 'Refresh');\n"
        "node.setAttribute('placeholder', 'Username');\n"
        "node.setAttribute('aria-label', 'Refresh');\n"
        "node.setAttribute('class', 'busy');\n"
        "node.setAttribute('data-state', 'ready');",
        encoding="utf-8",
    )
    findings = scan_admin_user_copy(root)
    assert AdminCopyFinding("static/admin.js", "<module>", "visible_attribute", "Refresh") in findings
    assert AdminCopyFinding("static/admin.js", "<module>", "visible_attribute", "Username") in findings
    assert not any(finding.text in {"title", "placeholder", "aria-label", "busy", "ready"} for finding in findings)


def test_admin_template_scanner_finds_single_word_visible_copy(tmp_path: Path) -> None:
    root = tmp_path
    (root / "static").mkdir()
    (root / "templates").mkdir()
    (root / "templates" / "admin.html").write_text(
        '<button>Refresh</button><span>Loading</span><input placeholder="Username"><button title="Refresh" aria-label="Refresh">...</button>',
        encoding="utf-8",
    )
    findings = scan_admin_user_copy(root)
    assert AdminCopyFinding("templates/admin.html", "button#-", "html_text", "Refresh") in findings
    assert AdminCopyFinding("templates/admin.html", "span#-", "html_text", "Loading") in findings
    assert AdminCopyFinding("templates/admin.html", "input#-", "placeholder", "Username") in findings
    assert AdminCopyFinding("templates/admin.html", "button#-", "title", "Refresh") in findings
    assert AdminCopyFinding("templates/admin.html", "button#-", "aria-label", "Refresh") in findings


def test_admin_copy_scanner_keeps_single_word_technical_arguments_out_of_findings(tmp_path: Path) -> None:
    root = tmp_path
    (root / "static").mkdir()
    (root / "templates").mkdir()
    (root / "static" / "admin.js").write_text(
        "element.classList.add('busy');\n"
        "document.addEventListener('click', handler);\n"
        "document.querySelector('#status');\n"
        "api('/admin/api/status');\n"
        "fetch('/admin/api/status');\n"
        "node.setAttribute('class', 'busy');\n"
        "node.setAttribute('data-state', 'ready');",
        encoding="utf-8",
    )
    assert not scan_admin_user_copy(root)


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


def test_studio_copy_scanner_keeps_shared_helper_natural_language_detection(tmp_path: Path) -> None:
    root = tmp_path
    nested = root / "static" / "studio"
    nested.mkdir(parents=True)
    (root / "templates").mkdir()
    (nested / "future.js").write_text(
        "function render() {\n"
        "  setProgress('Value must be > 0');\n"
        "  setProgress('low-vram protection enabled');\n"
        "  setProgress('中文可见文案');\n"
        "}",
        encoding="utf-8",
    )
    findings = scan_studio_user_copy(root)
    for text in ("Value must be > 0", "low-vram protection enabled", "中文可见文案"):
        assert StudioCopyFinding("static/studio/future.js", "render", "progress", text) in findings


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
