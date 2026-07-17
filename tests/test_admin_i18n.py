from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
ADMIN_HTML = ROOT / "src" / "kokoro_tts" / "templates" / "admin.html"
ADMIN_JS = ROOT / "src" / "kokoro_tts" / "static" / "admin.js"


def test_b2a_template_localizes_only_authorized_static_action_nodes() -> None:
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

    static_actions = {
        "refresh-btn": "action.refresh",
        "clear-cache-btn": "action.clear_cache",
        "unload-btn": "action.unload",
        "force-unload-btn": "action.force_stop",
        "reset-runtime-config-btn": "action.reset_runtime_config",
        "save-config-btn": "action.save_config",
        "download-diagnostics-btn": "action.download_diagnostics",
        "export-env-btn": "action.export_env",
    }
    for node_id, key in static_actions.items():
        node = re.search(rf"<[^>]+\bid=\"{node_id}\"[^>]*>", html)
        assert node, node_id
        assert f'data-i18n="{key}"' in node.group(0), node_id

    update_actions = {
        "update-release-link": "action.view_release_notes",
        "check-update-btn": "action.check_update",
    }
    for node_id, key in update_actions.items():
        node = re.search(rf"<[^>]+\bid=\"{node_id}\"[^>]*>", html)
        assert node, node_id
        assert f'data-i18n="{key}"' in node.group(0), node_id

    api_key_actions = {
        "reveal-key-btn": "action.reveal_api_key",
        "rotate-key-btn": "action.rotate_api_key",
    }
    for node_id, key in api_key_actions.items():
        node = re.search(rf"<[^>]+\bid=\"{node_id}\"[^>]*>", html)
        assert node, node_id
        assert f'data-i18n="{key}"' in node.group(0), node_id

    studio_link = re.search(r'<a\s+class="ghost-button small"\s+href="/"\s+data-i18n="([^"]+)">前往 Studio</a>', html)
    assert studio_link
    assert studio_link.group(1) == "action.open_studio"

    for node_id in (
        "admin-health-pill",
        "runtime-config-note",
        "update-message",
        "api-key-status",
        "default-admin-warning",
        "admin-credentials-feedback",
        "admin-toast",
        "admin-json",
    ):
        node = re.search(rf"<[^>]+\bid=\"{node_id}\"[^>]*>", html)
        assert node, node_id
        assert "data-i18n" not in node.group(0), node_id

    dictionary_heading = re.search(r'<h2\s+data-i18n="([^"]+)">文本与词典</h2>', html)
    assert dictionary_heading
    assert dictionary_heading.group(1) == "section.dictionary.title"

    admin_js = ADMIN_JS.read_text(encoding="utf-8")
    assert "{ key: 'config.text', labelKey: 'nav.config.text' }" in admin_js
    for node_id, key in {
        "admin-username-input": "credentials.username_placeholder",
        "admin-password-input": "credentials.password_placeholder",
    }.items():
        node = re.search(rf"<[^>]+\bid=\"{node_id}\"[^>]*>", html)
        assert node and f'data-i18n-placeholder="{key}"' in node.group(0)


def test_b2a_model_action_properties_use_exact_action_keys() -> None:
    source = ADMIN_JS.read_text(encoding="utf-8")
    copy_source = source[source.index("function currentAdminPresentationCopy") : source.index("const $ =")]
    assert {
        "load": "action.load",
        "switch": "action.switch",
        "unload": "action.unload",
        "forceStop": "action.force_stop",
        "checkAssets": "action.check_assets",
        "repairAssets": "action.repair_assets",
    } == {
        property: key
        for property, key in re.findall(r"\b(load|switch|unload|forceStop|checkAssets|repairAssets): t\('([^']+)'\)", copy_source)
    }


def test_b2b_action_feedback_uses_static_translation_keys_without_changing_action_shapes() -> None:
    source = ADMIN_JS.read_text(encoding="utf-8")

    def function_body(name: str, next_name: str) -> str:
        return source[source.index(f"async function {name}") : source.index(f"async function {next_name}")]

    load = function_body("loadModel", "switchModel")
    switch = function_body("switchModel", "unloadModel")
    unload = function_body("unloadModel", "checkAsset")
    check = function_body("checkAsset", "repairAsset")
    repair = function_body("repairAsset", "saveConfig")
    save = function_body("saveConfig", "applyProfile")
    profile = source[source.index("async function applyProfile") : source.index("document.addEventListener('click'")]
    click = source[source.index("document.addEventListener('click'") : source.index("document.addEventListener('angevoice:locale-changed'")]

    for body, keys in (
        (load, ("toast.model_loading", "toast.model_loaded")),
        (switch, ("toast.model_switching", "toast.model_switched")),
        (check, ("toast.asset_check_ready", "toast.asset_check_missing")),
        (repair, ("confirm.repair_asset", "toast.asset_repair_complete", "toast.asset_repair_incomplete")),
        (profile, ("confirm.apply_public_hardened", "toast.profile_applied")),
        (click, ("toast.action_failed",)),
    ):
        for key in keys:
            assert f"t('{key}'" in body

    assert "t('toast.model_unloaded')" in unload
    assert "t('toast.force_unloaded')" in unload
    assert "force && !confirm(t('confirm.force_unload_model', { model: modelId }))" in unload
    assert "t('toast.asset_check_ready', { model: modelId })" in check
    assert "t('toast.asset_check_missing', { model: modelId })" in check
    assert "t('confirm.repair_asset', { model: modelId })" in repair
    assert "JSON.stringify({force_unload: false})" in repair
    assert "if (!changed)" in save
    assert save.index("if (!changed)") < save.index("else if ((result.rebuilt_models || []).length)") < save.index("else if (result.model_rebuild_required)")
    for key in ("toast.config_unchanged", "toast.config_saved_rebuilt", "toast.config_saved_rebuild_pending", "toast.config_saved"):
        assert f"t('{key}'" in save
    assert "JSON.stringify({model: modelId, load: true, unload_previous: false})" in switch
    assert "toast(t('toast.action_failed', { message: err.message }), true);" in click
    assert not re.search(r"\bt\s*\(\s*(?!['\"])" , "\n".join((load, switch, unload, check, repair, save, profile, click)))


def test_b2b_static_handlers_use_exact_keys_without_migrating_b3() -> None:
    source = ADMIN_JS.read_text(encoding="utf-8")
    handlers = source[source.index("$('reset-runtime-config-btn')") : source.index("$('reveal-key-btn')")]
    for key in (
        "confirm.reset_runtime_config",
        "toast.runtime_config_cleared",
        "toast.runtime_config_not_found",
        "toast.refreshed",
        "toast.cache_cleared",
        "confirm.unload_all",
        "toast.idle_models_unloaded",
    ):
        assert f"t('{key}'" in handlers
    assert "toast(t('toast.diagnostics_downloaded'))" in source
    assert "check-update-btn').onclick = () => checkUpdate({force: true}).catch(err => toast(err.message, true))" in source


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
        "renderApiKeyStatusForLocale",
        "renderQuality",
        "renderRequests",
        "renderConfigFormsForLocale",
        "renderUpdate",
        "renderCredentialFeedback",
    ]
    assert "renderSecurity(lastData, { preserveApiKeyStatus: true })" in body
    assert len(re.findall(r"\brenderMetrics\s*\(", body)) == 1
    assert not re.search(r"\brenderHealth\s*\(", body)
    for forbidden in (
        "refresh",
        "api",
        "fetch",
        "checkUpdate",
        "renderConfigForms",
        "renderProfiles",
        "collectConfigValues",
    ):
        assert not re.search(rf"\b{forbidden}\s*\(", body)
    for protected_node in (
        "admin-credentials-feedback",
        "data-config-field",
    ):
        assert protected_node not in body


def test_b1b1_security_rerender_preserves_api_key_status_only_for_locale_changes() -> None:
    source = ADMIN_JS.read_text(encoding="utf-8")
    security = source[source.index("function renderSecurity(") : source.index("function renderQuality(")]
    refresh = source[source.index("async function refresh()") : source.index("async function loadModel(")]

    assert "function renderSecurity(data, { preserveApiKeyStatus = false } = {})" in security
    assert "if (!preserveApiKeyStatus) {\n    renderApiKeySummary(presentation);\n  }" in security
    assert "$('security-summary').innerHTML = presentation.summaryHtml;" in security
    assert "$('default-admin-warning')" in security
    assert "renderSecurity(status);" in refresh
    assert "localStorage" not in security
    assert ".dataset" not in security
    assert not re.search(r"\b(?:let|const|var)\s+(?:last|current|revealed|rotated|cached)(?:ApiKey|Key|Secret)\b", source)


def test_b3a_locale_listener_preserves_config_credential_and_toast_state() -> None:
    body = _locale_listener_body(ADMIN_JS.read_text(encoding="utf-8"))
    for forbidden in (
        "renderConfigForms",
        "setCredentialFeedback",
        "toggleCredentialConfirmation",
    ):
        assert not re.search(rf"\b{forbidden}\s*\(", body)
    assert "renderConfigFormsForLocale(lastConfigPayload)" in body
    assert "renderUpdate(lastUpdateData)" in body
    assert "renderRuntimeConfigNote" not in body


def test_b3b_api_key_display_keeps_secrets_in_dedicated_dom_nodes() -> None:
    source = ADMIN_JS.read_text(encoding="utf-8")
    helpers = source[source.index("function renderApiKeySummary") : source.index("function renderSecurity")]
    listener = _locale_listener_body(source)
    reveal = source[source.index("$('reveal-key-btn')") : source.index("$('rotate-key-btn')")]
    rotate = source[source.index("$('rotate-key-btn')") : source.index("function setCredentialFeedback")]

    assert "let apiKeyDisplayMode = 'summary';" in source
    assert "apiKeyDisplayMode = 'summary';" in helpers
    assert "apiKeyDisplayMode = 'disabled';" in helpers
    assert "apiKeyDisplayMode = mode;" in helpers
    assert "document.createElement('span')" in helpers
    assert "document.createElement('code')" in helpers
    assert "prefix.dataset.apiKeyPrefix = '';" in helpers
    assert "secret.dataset.apiKeySecret = '';" in helpers
    assert "holder.replaceChildren(prefix, secret);" in helpers
    assert "innerHTML" not in helpers
    assert "localStorage" not in helpers
    assert "sessionStorage" not in helpers
    assert "data-api-key-secret" not in helpers[helpers.index("function renderApiKeyStatusForLocale") :]
    assert "t(apiKey" not in helpers
    assert "t(apiKey" not in reveal
    assert "t(data.api_key" not in reveal
    assert "renderApiKeySecretStatus('current', data.api_key);" in reveal
    assert "renderApiKeyDisabledStatus();" in reveal
    assert "api('/admin/api/security?reveal=true')" in reveal
    assert "confirm(t('confirm.rotate_api_key'))" in rotate
    assert "method: 'POST'" in rotate
    assert "JSON.stringify({rotate: true})" in rotate
    assert "renderApiKeySecretStatus('new', data.api_key);" in rotate
    assert "toast(t('toast.api_key_rotated'));" in rotate
    assert "renderApiKeyStatusForLocale(lastData);" in listener
    assert listener.index("renderSecurity") < listener.index("renderApiKeyStatusForLocale") < listener.index("renderQuality")


def test_b3c_credentials_use_semantic_feedback_state_and_static_i18n_contracts() -> None:
    html = ADMIN_HTML.read_text(encoding="utf-8")
    source = ADMIN_JS.read_text(encoding="utf-8")

    for selector, key in {
        r"<h3[^>]+": "credentials.title",
        r"<span[^>]+": "credentials.default_account_intro",
        r"<span[^>]+": "credentials.default_account_guidance",
    }.items():
        assert re.search(rf"{selector}data-i18n=\"{re.escape(key)}\"", html)
    for node_id, key in {
        "admin-username-input": "credentials.username_placeholder",
        "admin-password-input": "credentials.password_placeholder",
        "save-admin-credentials-btn": "action.save_admin_credentials",
        "confirm-admin-credentials-btn": "action.confirm_admin_credentials",
        "cancel-admin-credentials-btn": "action.cancel",
    }.items():
        node = re.search(rf"<[^>]+\bid=\"{node_id}\"[^>]*>", html)
        assert node and f'data-i18n{"-placeholder" if "input" in node_id else ""}="{key}"' in node.group(0)
    for value in ("<code>admin</code>", "<code>admin123</code>", "PBKDF2"):
        assert value in html

    feedback = source[source.index("function renderCredentialFeedback") : source.index("function toggleCredentialConfirmation")]
    assert "let credentialFeedbackState = null;" in source
    assert "credentialFeedbackState = key ? { key, params: { ...params }, state } : null;" in feedback
    assert "textContent" in feedback
    assert "innerHTML" not in feedback
    assert not re.search(r"\bt\s*\(\s*(?!['\"])", feedback)
    for forbidden in ("admin-username-input", "admin-password-input", "localStorage", "sessionStorage", ".dataset"):
        assert forbidden not in feedback
    for key in (
        "credentials.confirm_save",
        "credentials.cancelled",
        "credentials.saving",
        "credentials.saved",
        "credentials.save_failed",
    ):
        assert f"'{key}'" in feedback

    save = source[source.index("$('save-admin-credentials-btn').onclick") : source.index("$('cancel-admin-credentials-btn').onclick")]
    cancel = source[source.index("$('cancel-admin-credentials-btn').onclick") : source.index("$('confirm-admin-credentials-btn').onclick")]
    confirm = source[source.index("$('confirm-admin-credentials-btn').onclick") :]
    assert "toast(t('credentials.enter_username_password'), true)" in save
    assert "setCredentialFeedback('credentials.confirm_save', {}, credentialPendingState)" in save
    assert "setCredentialFeedback('credentials.cancelled')" in cancel
    assert confirm.count("toast(t('credentials.enter_username_password'), true)") == 1
    assert "setCredentialFeedback('credentials.saving', {}, credentialPendingState)" in confirm
    assert "setCredentialFeedback('credentials.saved', {}, credentialSuccessState)" in confirm
    assert "const params = { message: err.message };" in confirm
    assert "setCredentialFeedback('credentials.save_failed', params, credentialErrorState)" in confirm
    assert "toast(t('credentials.save_failed', params), true)" in confirm
    assert "toast(t('toast.credentials_saved'));" in confirm
    assert "api('/admin/api/security/credentials'," in confirm
    assert "method: 'PUT'" in confirm
    assert "headers: {'Content-Type': 'application/json'}" in confirm
    assert "JSON.stringify({username, password})" in confirm
    password_clear = confirm.index("$('admin-password-input').value = '';")
    assert password_clear < confirm.index("toggleCredentialConfirmation(false);", password_clear)
    assert "finally" in confirm and confirm.index("finally") < confirm.index("confirmBtn.disabled = false;")

    listener = _locale_listener_body(source)
    assert listener.rstrip().endswith("renderCredentialFeedback();")
    assert "renderCredentialFeedback" not in re.sub(r"renderCredentialFeedback\(\);", "", listener)


def test_b3a_update_lifecycle_uses_raw_cached_data_and_static_translation_keys() -> None:
    source = ADMIN_JS.read_text(encoding="utf-8")
    update = source[source.index("function renderUpdate") : source.index("async function checkUpdate")]
    check = source[source.index("async function checkUpdate") : source.index("function renderMetrics")]
    listener = _locale_listener_body(source)

    assert "let lastUpdateData = null;" in source
    assert "let updateCheckInProgress = false;" in source
    assert "lastUpdateData = data;" in update
    assert "localStorage" not in update
    assert ".dataset" not in update
    assert "updateCheckInProgress ? t('update.checking') : t('action.check_update')" in update
    for key in (
        "update.checking",
        "update.disabled",
        "update.available",
        "update.error",
        "update.up_to_date",
        "update.not_checked",
    ):
        assert f"t('{key}'" in update
    assert "{ latest: data.latest_version, current }" in update
    assert "{ current, error: data.error }" in update
    assert "message.textContent = t('update.checking');" in update
    assert "data.release_url" in update
    assert "link.href = data.release_url;" in update

    assert check.index("updateCheckInProgress = true;") < check.index("renderUpdate(lastUpdateData || {});") < check.index("await api(`/admin/api/update/check?force=${force ? 'true' : 'false'}`")
    assert "{ method: 'POST' }" in check
    assert "toast(t('toast.update_available', { version: data.latest_version }))" in check
    assert "if (!silent && data.error) toast(data.error, true);" in check
    assert "toast(t('toast.update_check_failed', { message: err.message }), true);" in check
    assert check.index("updateCheckInProgress = false;") < check.rindex("renderUpdate(lastUpdateData || {});")
    assert "btn.textContent" not in check
    assert "document" not in check

    assert "if (lastUpdateData) renderUpdate(lastUpdateData);" in listener
    assert re.findall(r"\b(render[A-Za-z]+)\s*\(", listener) == [
        "renderAdminSubnav",
        "renderMetrics",
        "renderModels",
        "renderSecurity",
        "renderApiKeyStatusForLocale",
        "renderQuality",
        "renderRequests",
        "renderConfigFormsForLocale",
        "renderUpdate",
        "renderCredentialFeedback",
    ]
    for forbidden in ("checkUpdate", "refresh", "api", "fetch", "renderProfiles", "collectConfigValues"):
        assert not re.search(rf"\b{forbidden}\s*\(", listener)


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
