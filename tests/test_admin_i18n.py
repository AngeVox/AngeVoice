from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
ADMIN_HTML = ROOT / "src" / "kokoro_tts" / "templates" / "admin.html"
ADMIN_JS = ROOT / "src" / "kokoro_tts" / "static" / "admin.js"


def test_b1a_template_localizes_only_passive_admin_shell_nodes() -> None:
    html = ADMIN_HTML.read_text(encoding="utf-8")
    for key in (
        "page.title",
        "header.console",
        "nav.overview",
        "nav.models",
        "nav.config",
        "nav.security",
        "nav.api",
        "section.config.group_aria",
        "section.dictionary.title",
        "section.dictionary.description",
        "section.raw_state.title",
    ):
        assert key in html

    for node_id in (
        "admin-health-pill",
        "runtime-config-note",
        "update-message",
        "api-key-status",
        "default-admin-warning",
        "admin-credentials-feedback",
        "admin-toast",
        "admin-json",
        "refresh-btn",
        "clear-cache-btn",
        "unload-btn",
        "force-unload-btn",
        "reset-runtime-config-btn",
        "save-config-btn",
        "download-diagnostics-btn",
        "export-env-btn",
        "update-release-link",
        "check-update-btn",
        "reveal-key-btn",
        "rotate-key-btn",
    ):
        node = re.search(rf"<[^>]+\bid=\"{node_id}\"[^>]*>", html)
        assert node, node_id
        assert "data-i18n" not in node.group(0), node_id

    dictionary_heading = re.search(r'<h2\s+data-i18n="([^"]+)">文本与词典</h2>', html)
    assert dictionary_heading
    assert dictionary_heading.group(1) == "section.dictionary.title"

    admin_js = ADMIN_JS.read_text(encoding="utf-8")
    assert "{ key: 'config.text', labelKey: 'nav.config.text' }" in admin_js


def _locale_listener_body(source: str) -> str:
    listener = re.search(
        r"document\.addEventListener\('angevoice:locale-changed', \(\) => \{(?P<body>.*?)\n\}\);",
        source,
        re.DOTALL,
    )
    assert listener
    return listener.group("body")


def test_b1b2_locale_listener_rerenders_only_safe_cached_regions() -> None:
    source = ADMIN_JS.read_text(encoding="utf-8")
    body = _locale_listener_body(source)
    assert re.findall(r"\b(render[A-Za-z]+)\s*\(", body) == [
        "renderAdminSubnav",
        "renderMetrics",
        "renderModels",
        "renderSecurity",
        "renderQuality",
        "renderRequests",
        "renderConfigFormsForLocale",
    ]
    assert "renderSecurity(lastData, { preserveApiKeyStatus: true })" in body
    assert len(re.findall(r"\brenderMetrics\s*\(", body)) == 1
    assert not re.search(r"\brenderHealth\s*\(", body)
    for forbidden in (
        "refresh",
        "api",
        "fetch",
        "checkUpdate",
        "renderUpdate",
        "renderConfigForms",
        "renderProfiles",
        "collectConfigValues",
    ):
        assert not re.search(rf"\b{forbidden}\s*\(", body)
    for protected_node in (
        "api-key-status",
        "update-message",
        "admin-credentials-feedback",
        "data-config-field",
    ):
        assert protected_node not in body


def test_b1b1_security_rerender_preserves_api_key_status_only_for_locale_changes() -> None:
    source = ADMIN_JS.read_text(encoding="utf-8")
    security = source[source.index("function renderSecurity(") : source.index("function renderQuality(")]
    refresh = source[source.index("async function refresh()") : source.index("async function loadModel(")]

    assert "function renderSecurity(data, { preserveApiKeyStatus = false } = {})" in security
    assert "if (!preserveApiKeyStatus) {\n    $('api-key-status').textContent = presentation.apiKeyStatus;\n  }" in security
    assert "$('security-summary').innerHTML = presentation.summaryHtml;" in security
    assert "$('default-admin-warning')" in security
    assert "renderSecurity(status);" in refresh
    assert "localStorage" not in security
    assert ".dataset" not in security
    assert not re.search(r"\b(?:let|const|var)\s+(?:revealed|rotated|cached)(?:ApiKey|Key|Secret)\b", source)


def test_b1b2_locale_listener_preserves_config_update_and_credential_state() -> None:
    body = _locale_listener_body(ADMIN_JS.read_text(encoding="utf-8"))
    for forbidden in (
        "renderConfigForms",
        "renderUpdate",
        "setCredentialFeedback",
        "toggleCredentialConfirmation",
    ):
        assert not re.search(rf"\b{forbidden}\s*\(", body)
    assert "renderConfigFormsForLocale(lastConfigPayload)" in body
    assert "renderRuntimeConfigNote" not in body


def test_b1b2_config_locale_rerender_snapshots_only_config_form_state() -> None:
    source = ADMIN_JS.read_text(encoding="utf-8")
    capture = source[source.index("function captureConfigFormUiState") : source.index("function restoreConfigFormUiState")]
    restore = source[source.index("function restoreConfigFormUiState") : source.index("function renderConfigFormsForLocale")]
    wrapper = source[source.index("function renderConfigFormsForLocale") : source.index("function renderProfiles")]

    assert "document.querySelectorAll('[data-config-field]')" in capture
    for protected_node in (
        "admin-username-input",
        "admin-password-input",
        "api-key-status",
        "env-patch",
        "admin-json",
        "localStorage",
        "sessionStorage",
    ):
        assert protected_node not in capture
        assert protected_node not in restore
    assert "field.type === 'checkbox'" in capture
    assert "{ checked: field.checked }" in capture
    assert "{ value: field.value }" in capture
    assert "field.checked = fieldState.checked" in restore
    assert "field.value = fieldState.value" in restore
    for forbidden in ("collectConfigValues", "Number.parseFloat", "Number.parseInt", "miBToBytes"):
        assert forbidden not in capture
        assert forbidden not in restore
    assert wrapper.index("captureConfigFormUiState()") < wrapper.index("renderConfigForms(payload)") < wrapper.index("restoreConfigFormUiState(state)")
    assert wrapper.count("renderConfigForms(payload)") == 1
    assert "activeGroup = state.activeGroup" in wrapper
    assert not re.search(r"\b(?:let|const|var)\s+\w*(?:draft|cache)\w*", source[source.index("const $ =") : source.index("function captureConfigFormUiState")], re.IGNORECASE)


def test_b1b2_config_locale_rerender_restores_focus_selection_and_scroll() -> None:
    source = ADMIN_JS.read_text(encoding="utf-8")
    capture = source[source.index("function captureConfigFormUiState") : source.index("function restoreConfigFormUiState")]
    restore = source[source.index("function restoreConfigFormUiState") : source.index("function renderConfigFormsForLocale")]

    assert "document.activeElement === field" in capture
    assert "focusedKey" in capture
    assert "node.dataset.configField === state.focusedKey" in restore
    assert "focusedField.focus({ preventScroll: true })" in restore
    assert "focusedField.focus();" in restore
    assert "typeof field.selectionStart === 'number'" in capture
    assert "typeof field.setSelectionRange !== 'function'" in restore
    assert "field.setSelectionRange(start, end, fieldState.selection.direction)" in restore
    assert "Math.min" in restore
    assert "window.scrollX" in capture
    assert "window.scrollY" in capture
    assert "window.scrollTo(state.scrollX, state.scrollY)" in restore
    assert "fields.set(key, state)" in capture
    assert "fields.forEach" in restore


def test_b1b2_keeps_normal_refresh_and_group_switch_on_normal_config_rendering() -> None:
    source = ADMIN_JS.read_text(encoding="utf-8")
    refresh = source[source.index("async function refresh()") : source.index("async function loadModel(")]
    group_click = source[source.index("document.addEventListener('click'") : source.index("document.addEventListener('angevoice:locale-changed'")]

    assert "renderConfigForms(configPayload);" in refresh
    assert "renderConfigFormsForLocale" not in refresh
    assert "renderConfigForms(lastConfigPayload);" in group_click
    assert "renderConfigFormsForLocale" not in group_click


def test_b1a_keeps_technical_identifiers_as_template_literals() -> None:
    html = ADMIN_HTML.read_text(encoding="utf-8")
    for value in ("AngeVoice Studio", ">Studio<", ">API<", ">Admin<", "ENV Patch", "Raw State", "PBKDF2"):
        assert value in html
