from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
ADMIN_HTML = ROOT / "src" / "kokoro_tts" / "templates" / "admin.html"
ADMIN_JS = ROOT / "src" / "kokoro_tts" / "static" / "admin.js"
ADMIN_CSS = ROOT / "src" / "kokoro_tts" / "static" / "admin.css"
ADMIN_EN_MESSAGES = ROOT / "src" / "kokoro_tts" / "static" / "locale" / "admin" / "messages.en.js"

FINAL_METADATA_COPY_FIXUPS = {
    "config.field.moss_segment_length.help": (
        "The default is 120, trading a little throughput for more stable mixed Chinese-English "
        "and long-text output. When more VRAM is available, you can switch to the long narration profile."
    ),
    "config.field.moss_realtime_streaming_decode.help": (
        "Enabled by default to preserve the official MOSS frame-by-frame streaming experience. "
        "You can disable it in Admin if a specific device exhibits boundary noise or VRAM pressure."
    ),
    "config.field.moss_process_isolation_enabled.help": (
        "Keeping this enabled is recommended. If a timeout or low-level hang occurs, the isolated worker "
        "can be terminated and recovered automatically instead of leaving the engine permanently blocked."
    ),
    "config.field.zipvoice_num_steps.help": (
        "More steps may improve quality but increase latency. Starting with 8 is recommended on CPU/NAS; "
        "GPU users can test 16."
    ),
    "config.profile.clone_quality.description": (
        "Recommended for 16GB+ configurations. Time to first audio is slower, but cloning is more stable."
    ),
}

TEXT_CONFIG_METADATA_KEYS = {
    "config.field.angevoice_tn_engine.label",
    "config.field.angevoice_tn_engine.help",
    "config.field.angevoice_tn_engine.choice.wetext",
    "config.field.angevoice_tn_engine.choice.legacy",
    "config.field.angevoice_tn_engine.choice.off",
    "config.field.text_single_newline_policy.label",
    "config.field.text_single_newline_policy.help",
    "config.field.text_single_newline_policy.choice.auto",
    "config.field.text_single_newline_policy.choice.preserve",
    "config.field.text_single_newline_policy.choice.space",
    "config.field.moss_apply_angevoice_rules.label",
    "config.field.moss_apply_angevoice_rules.help",
    "config.field.moss_apply_angevoice_rules.choice.auto",
    "config.field.moss_apply_angevoice_rules.choice.true",
    "config.field.moss_apply_angevoice_rules.choice.false",
}

REMAINING_ADMIN_METADATA_KEYS = frozenset(
    """
    config.field.default_speed.label
    config.field.default_speed.help
    config.field.segment_length.label
    config.field.segment_length.help
    config.field.moss_segment_length.label
    config.field.moss_segment_length.help
    config.field.moss_voice_clone_max_text_tokens.label
    config.field.moss_max_new_frames.label
    config.field.moss_max_silence_ms.label
    config.field.moss_max_silence_ms.help
    config.field.moss_crossfade_ms.label
    config.field.moss_segment_pause_ms.label
    config.field.moss_runtime_pause_max_ms.label
    config.field.moss_output_target_peak.label
    config.field.moss_output_gain.label
    config.field.moss_audio_polish_enabled.label
    config.field.moss_trim_silence_enabled.label
    config.field.moss_mixed_english_policy.label
    config.field.moss_mixed_english_policy.help
    config.field.moss_mixed_english_policy.choice.translate
    config.field.moss_mixed_english_policy.choice.preserve
    config.field.moss_mixed_english_policy.choice.spell
    config.field.moss_realtime_streaming_decode.label
    config.field.moss_realtime_streaming_decode.help
    config.field.stream_chunk_seconds.label
    config.field.stream_prebuffer_seconds.label
    config.field.kokoro_process_isolation_enabled.label
    config.field.kokoro_process_isolation_enabled.help
    config.field.moss_stream_chunk_seconds.label
    config.field.moss_stream_prebuffer_seconds.label
    config.field.moss_stream_prebuffer_seconds.help
    config.field.moss_stream_queue_max_items.label
    config.field.max_concurrent_requests.label
    config.field.request_timeout_seconds.label
    config.field.model_idle_timeout_seconds.label
    config.field.model_idle_check_interval.label
    config.field.model_idle_unload_current.label
    config.field.restart_after_idle_unload_enabled.label
    config.field.restart_after_idle_unload_enabled.help
    config.field.restart_after_idle_unload_delay_seconds.label
    config.field.restart_after_idle_unload_delay_seconds.help
    config.field.restart_after_idle_unload_cooldown_seconds.label
    config.field.restart_after_idle_unload_cooldown_seconds.help
    config.field.restart_after_idle_unload_exit_code.label
    config.field.restart_after_idle_unload_exit_code.help
    config.field.startup_preload_enabled.label
    config.field.startup_preload_enabled.help
    config.field.startup_preload_model.label
    config.field.startup_preload_model.help
    config.field.startup_preload_model.choice.kokoro
    config.field.startup_preload_model.choice.moss
    config.field.startup_preload_model.choice.zipvoice
    config.field.engine_process_kill_grace_seconds.label
    config.field.engine_process_kill_grace_seconds.help
    config.field.cache_max_items.label
    config.field.cache_max_bytes.label
    config.field.cache_max_bytes.help
    config.field.cache_skip_text_over_chars.label
    config.field.cache_skip_text_over_chars.help
    config.field.cache_skip_audio_over_bytes.label
    config.field.cache_skip_audio_over_bytes.help
    config.field.save_outputs.label
    config.field.ffmpeg_enabled.label
    config.field.ffmpeg_enabled.help
    config.field.ffmpeg_binary.label
    config.field.ffmpeg_binary.help
    config.field.mp3_bitrate.label
    config.field.mp3_bitrate.help
    config.field.audio_opus_bitrate.label
    config.field.audio_opus_bitrate.help
    config.field.audio_aac_bitrate.label
    config.field.audio_aac_bitrate.help
    config.field.ffmpeg_timeout_seconds.label
    config.field.output_max_files.label
    config.field.moss_vram_guard_enabled.label
    config.field.moss_vram_guard_enabled.help
    config.field.moss_vram_safe_free_mb.label
    config.field.moss_vram_critical_free_mb.label
    config.field.moss_low_vram_segment_length.label
    config.field.moss_low_vram_max_new_frames.label
    config.field.moss_low_vram_text_tokens.label
    config.field.moss_disable_full_codec_after_oom.label
    config.field.moss_full_codec_oom_cooldown_seconds.label
    config.field.moss_vram_snapshot_ttl_seconds.label
    config.field.moss_vram_snapshot_ttl_seconds.help
    config.field.rate_limit_qps.label
    config.field.rate_limit_burst.label
    config.field.max_queue_length.label
    config.field.websocket_max_connections.label
    config.field.websocket_max_connections.help
    config.field.websocket_max_message_bytes.label
    config.field.websocket_max_message_bytes.help
    config.field.trust_proxy_headers.label
    config.field.public_status_endpoints.label
    config.field.model_source.label
    config.field.model_source.choice.auto
    config.field.model_source.choice.modelscope
    config.field.model_source.choice.huggingface
    config.field.model_source.choice.offline
    config.field.moss_hf_repo.label
    config.field.moss_hf_repo.help
    config.field.moss_prompt_audio_max_seconds.label
    config.field.moss_output_peak_normalize_enabled.label
    config.field.moss_output_declick_enabled.label
    config.field.moss_output_edge_fade_ms.label
    config.field.moss_trim_silence_db.label
    config.field.moss_quality_gate_enabled.label
    config.field.moss_process_isolation_enabled.label
    config.field.moss_process_isolation_enabled.help
    config.field.zipvoice_process_isolation_enabled.label
    config.field.zipvoice_process_isolation_enabled.help
    config.field.zipvoice_num_steps.label
    config.field.zipvoice_num_steps.help
    config.field.zipvoice_prompt_audio_max_seconds.label
    config.field.zipvoice_prompt_audio_max_seconds.help
    config.field.zipvoice_remove_long_sil.label
    config.field.zipvoice_remove_long_sil.help
    config.field.zipvoice_guidance_scale.label
    config.field.zipvoice_t_shift.label
    config.field.zipvoice_target_rms.label
    config.field.zipvoice_feat_scale.label
    config.group.kokoro.label
    config.group.moss.label
    config.group.zipvoice.label
    config.group.text.label
    config.group.service.label
    config.group.audio.label
    config.group.security.label
    config.profile.deploy_lan_default.label
    config.profile.deploy_lan_default.description
    config.profile.deploy_public_hardened.label
    config.profile.deploy_public_hardened.description
    config.profile.nas_stable.label
    config.profile.nas_stable.description
    config.profile.nas_deep_sleep_cpu.label
    config.profile.nas_deep_sleep_cpu.description
    config.profile.balanced.label
    config.profile.balanced.description
    config.profile.long_narration.label
    config.profile.long_narration.description
    config.profile.low_latency.label
    config.profile.low_latency.description
    config.profile.clone_quality.label
    config.profile.clone_quality.description
    """.split()
)

REMAINING_ADMIN_FIELD_KEYS = frozenset(
    """
    default_speed
    segment_length
    moss_segment_length
    moss_voice_clone_max_text_tokens
    moss_max_new_frames
    moss_max_silence_ms
    moss_crossfade_ms
    moss_segment_pause_ms
    moss_runtime_pause_max_ms
    moss_output_target_peak
    moss_output_gain
    moss_audio_polish_enabled
    moss_trim_silence_enabled
    moss_mixed_english_policy
    moss_realtime_streaming_decode
    stream_chunk_seconds
    stream_prebuffer_seconds
    kokoro_process_isolation_enabled
    moss_stream_chunk_seconds
    moss_stream_prebuffer_seconds
    moss_stream_queue_max_items
    max_concurrent_requests
    request_timeout_seconds
    model_idle_timeout_seconds
    model_idle_check_interval
    model_idle_unload_current
    restart_after_idle_unload_enabled
    restart_after_idle_unload_delay_seconds
    restart_after_idle_unload_cooldown_seconds
    restart_after_idle_unload_exit_code
    startup_preload_enabled
    startup_preload_model
    engine_process_kill_grace_seconds
    cache_max_items
    cache_max_bytes
    cache_skip_text_over_chars
    cache_skip_audio_over_bytes
    save_outputs
    ffmpeg_enabled
    ffmpeg_binary
    mp3_bitrate
    audio_opus_bitrate
    audio_aac_bitrate
    ffmpeg_timeout_seconds
    output_max_files
    moss_vram_guard_enabled
    moss_vram_safe_free_mb
    moss_vram_critical_free_mb
    moss_low_vram_segment_length
    moss_low_vram_max_new_frames
    moss_low_vram_text_tokens
    moss_disable_full_codec_after_oom
    moss_full_codec_oom_cooldown_seconds
    moss_vram_snapshot_ttl_seconds
    rate_limit_qps
    rate_limit_burst
    max_queue_length
    websocket_max_connections
    websocket_max_message_bytes
    trust_proxy_headers
    public_status_endpoints
    model_source
    moss_hf_repo
    moss_prompt_audio_max_seconds
    moss_output_peak_normalize_enabled
    moss_output_declick_enabled
    moss_output_edge_fade_ms
    moss_trim_silence_db
    moss_quality_gate_enabled
    moss_process_isolation_enabled
    zipvoice_process_isolation_enabled
    zipvoice_num_steps
    zipvoice_prompt_audio_max_seconds
    zipvoice_remove_long_sil
    zipvoice_guidance_scale
    zipvoice_t_shift
    zipvoice_target_rms
    zipvoice_feat_scale
    """.split()
)

REMAINING_ADMIN_GROUP_KEYS = frozenset("kokoro moss zipvoice text service audio security".split())
REMAINING_ADMIN_PROFILE_KEYS = frozenset("deploy_lan_default deploy_public_hardened nas_stable nas_deep_sleep_cpu balanced long_narration low_latency clone_quality".split())



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
    assert (
        save.index("if (!changed)")
        < save.index("else if ((result.rebuilt_models || []).length)")
        < save.index("else if (result.model_rebuild_required)")
        < save.index("else if ((result.restart_required || []).length)")
        < save.index("t('toast.config_saved', { count: changed })")
    )
    for key in (
        "toast.config_unchanged",
        "toast.config_saved_rebuilt",
        "toast.config_saved_rebuild_pending",
        "toast.config_saved_restart_required",
        "toast.config_saved",
    ):
        assert f"t('{key}'" in save
    assert "(result.restart_required || []).length" in save
    restart_fields = (
        "max_concurrent_requests",
        "startup_preload_enabled",
        "startup_preload_model",
        "rate_limit_qps",
        "rate_limit_burst",
        "max_queue_length",
        "websocket_max_connections",
        "websocket_max_message_bytes",
        "trust_proxy_headers",
        "moss_hf_repo",
    )
    assert not any(field in save for field in restart_fields)
    locale_root = ROOT / "src" / "kokoro_tts" / "static" / "locale" / "admin"
    for locale in ("zh-cn", "en"):
        catalog = (locale_root / f"messages.{locale}.js").read_text(encoding="utf-8")
        entry = re.search(
            r"'toast\.config_saved_restart_required':\s*'(?P<message>[^']+)'",
            catalog,
        )
        assert entry
        assert catalog.count("'toast.config_saved_restart_required':") == 1
        assert "{count}" in entry.group("message")
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
        "renderProfiles",
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
            "renderProfiles",
            "renderUpdate",
            "renderCredentialFeedback",
        ]
    for forbidden in ("checkUpdate", "refresh", "api", "fetch", "collectConfigValues"):
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


def test_text_config_metadata_overlay_uses_exact_static_keys_and_render_boundary() -> None:
    source = ADMIN_JS.read_text(encoding="utf-8")
    overlay = source[
        source.index("function localizeTextConfigField")
        : source.index("function renderConfigForms(")
    ]
    render = source[
        source.index("function renderConfigForms(")
        : source.index("function captureConfigFormUiState")
    ]
    listener = _locale_listener_body(source)

    assert {
        key
        for key in TEXT_CONFIG_METADATA_KEYS
        if overlay.count(f"t('{key}')") == 1
    } == TEXT_CONFIG_METADATA_KEYS
    assert len(re.findall(r"\bt\('config\.field\.[^']+'\)", overlay)) == 15
    assert not re.search(r"\bt\s*\(\s*(?:`|[A-Za-z_$])", overlay)
    assert "switch (field.key)" in overlay
    assert set(re.findall(r"case '([^']+)':", overlay)) == {
        "angevoice_tn_engine",
        "wetext",
        "legacy",
        "off",
        "text_single_newline_policy",
        "auto",
        "preserve",
        "space",
        "moss_apply_angevoice_rules",
        "true",
        "false",
    }
    assert "if (field?.group !== 'text') return field;" in overlay
    assert "default:\n      return field;" in overlay
    assert "renderRuntimeConfigNote(payload);" in render
    assert "const localizedPayload = localizedConfigPayload(payload);" in render
    assert "configPresentation(localizedPayload, activeGroup, currentAdminPresentationCopy())" in render
    assert "configPresentation(payload," not in render
    for forbidden in ("fetch(", "api(", "lastConfigPayload =", "payload.values ="):
        assert forbidden not in overlay
    for forbidden in ("fetch(", "api(", "refresh("):
        assert forbidden not in listener


def test_remaining_metadata_overlay_uses_exact_static_keys_and_scopes() -> None:
    source = ADMIN_JS.read_text(encoding="utf-8")
    copy_source = source[
        source.index("function currentRemainingAdminMetadataCopy")
        : source.index("function localizeTextConfigField")
    ]
    overlay = source[
        source.index("function currentRemainingAdminMetadataCopy")
        : source.index("function renderConfigForms(")
    ]
    references = re.findall(r"\bt\('([^']+)'\)", copy_source)
    assert len(references) == len(set(references)) == 144
    assert set(references) == REMAINING_ADMIN_METADATA_KEYS
    assert not re.search(r"\bt\s*\(\s*(?:`|[A-Za-z_$])", overlay)

    script = f"""
      const t = key => key;
      {copy_source}
      const copy = currentRemainingAdminMetadataCopy();
      console.log(JSON.stringify({{
        fieldKeys: Object.keys(copy.fields),
        groupKeys: Object.keys(copy.groups),
        profileKeys: Object.keys(copy.profiles),
      }}));
    """
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)
    assert set(result["fieldKeys"]) == REMAINING_ADMIN_FIELD_KEYS
    assert set(result["groupKeys"]) == REMAINING_ADMIN_GROUP_KEYS
    assert set(result["profileKeys"]) == REMAINING_ADMIN_PROFILE_KEYS
    assert len(result["fieldKeys"]) == 78
    assert len(result["groupKeys"]) == 7
    assert len(result["profileKeys"]) == 8


def test_remaining_metadata_overlay_is_used_for_forms_profiles_and_locale_rerender() -> None:
    source = ADMIN_JS.read_text(encoding="utf-8")
    forms = source[
        source.index("function renderConfigForms(")
        : source.index("function captureConfigFormUiState")
    ]
    profiles = source[
        source.index("function renderProfiles(")
        : source.index("function renderApiKeySummary")
    ]
    listener = _locale_listener_body(source)
    assert "const localizedPayload = localizedConfigPayload(payload);" in forms
    assert "configPresentation(localizedPayload, activeGroup, currentAdminPresentationCopy())" in forms
    assert "const localizedPayload = localizedConfigPayload(payload);" in profiles
    assert "profilesPresentation(localizedPayload)" in profiles
    assert "renderConfigFormsForLocale(lastConfigPayload);" in listener
    assert "renderProfiles(lastConfigPayload);" in listener
    for forbidden in ("fetch(", "api(", "refresh(", "PATCH", "applyProfile("):
        assert forbidden not in listener


def test_text_config_metadata_overlay_is_finite_nonmutating_and_value_preserving() -> None:
    source = ADMIN_JS.read_text(encoding="utf-8")
    overlay = source[
        source.index("function currentRemainingAdminMetadataCopy")
        : source.index("function renderConfigForms(")
    ]
    script = f"""
      const t = key => `translated:${{key}}`;
      {overlay}
      const unknownChoice = {{value: 'future', label: 'Future value', machine: {{stable: true}}}};
      const textUnknownChoice = {{value: 'future-text', label: 'Future text value'}};
      const profileValues = {{moss_segment_length: 160}};
      const payload = {{
        values: {{model_source: 'auto', angevoice_tn_engine: 'wetext'}},
        runtime_config: {{exists: true, field_count: 1}},
        schema: {{
          groups: [
            {{key: 'service', label: '服务与存储', machine: {{order: 1}}}},
            {{key: 'future-group', label: 'Future group'}},
          ],
          profiles: [
            {{key: 'balanced', label: '均衡推荐', description: '中文描述', values: profileValues}},
            {{key: 'future-profile', label: 'Future profile', values: {{future: true}}}},
          ],
          fields: [
            {{
              key: 'model_source',
              group: 'security',
              label: '模型下载源',
              help: 'Future-safe machine help',
              type: 'choice',
              default: 'auto',
              restart: false,
              choices: [
                {{value: 'auto', label: '自动'}},
                {{value: 'modelscope', label: 'ModelScope'}},
                {{value: 'huggingface', label: 'Hugging Face'}},
                {{value: 'offline', label: '离线'}},
                unknownChoice,
              ],
            }},
            {{
              key: 'angevoice_tn_engine',
              group: 'text',
              label: '默认文本处理',
              help: '中文帮助',
              choices: [
                {{value: 'wetext', label: '标准'}},
                {{value: 'legacy', label: '保守'}},
                {{value: 'off', label: '关闭'}},
                textUnknownChoice,
              ],
            }},
            {{key: 'future_field', group: 'future', label: 'Future field'}},
          ],
        }},
      }};
      const before = JSON.stringify(payload);
      const localized = localizedConfigPayload(payload);
      const withoutSchema = {{values: {{}}}};
      const futureOnly = {{
        schema: {{
          fields: [{{key: 'future_field'}}],
          groups: [{{key: 'future-group'}}],
          profiles: [{{key: 'future-profile'}}],
        }},
      }};
      console.log(JSON.stringify({{
        originalUnchanged: JSON.stringify(payload) === before,
        payloadCloned: localized !== payload,
        schemaCloned: localized.schema !== payload.schema,
        fieldsCloned: localized.schema.fields !== payload.schema.fields,
        valuesPreserved: localized.values === payload.values,
        runtimeConfigPreserved: localized.runtime_config === payload.runtime_config,
        groupsCloned: localized.schema.groups !== payload.schema.groups,
        profilesCloned: localized.schema.profiles !== payload.schema.profiles,
        knownFieldCloned: localized.schema.fields[0] !== payload.schema.fields[0],
        knownTextFieldCloned: localized.schema.fields[1] !== payload.schema.fields[1],
        unknownFieldPreserved: localized.schema.fields[2] === payload.schema.fields[2],
        knownChoiceValues: localized.schema.fields[0].choices.map(choice => choice.value),
        originalChoiceValues: payload.schema.fields[0].choices.map(choice => choice.value),
        knownChoicesCloned: localized.schema.fields[0].choices.slice(0, 4).every(
          (choice, index) => choice !== payload.schema.fields[0].choices[index]
        ),
        unknownChoicePreserved: localized.schema.fields[0].choices[4] === unknownChoice,
        textUnknownChoicePreserved: localized.schema.fields[1].choices[3] === textUnknownChoice,
        machineFieldMetadataPreserved:
          localized.schema.fields[0].type === payload.schema.fields[0].type
          && localized.schema.fields[0].default === payload.schema.fields[0].default
          && localized.schema.fields[0].restart === payload.schema.fields[0].restart,
        knownGroupCloned: localized.schema.groups[0] !== payload.schema.groups[0],
        unknownGroupPreserved: localized.schema.groups[1] === payload.schema.groups[1],
        groupMachineMetadataPreserved:
          localized.schema.groups[0].machine === payload.schema.groups[0].machine,
        knownProfileCloned: localized.schema.profiles[0] !== payload.schema.profiles[0],
        unknownProfilePreserved: localized.schema.profiles[1] === payload.schema.profiles[1],
        profileValuesPreserved: localized.schema.profiles[0].values === profileValues,
        missingSchemaPreserved: localizedConfigPayload(withoutSchema) === withoutSchema,
        futureOnlyPreserved: localizedConfigPayload(futureOnly) === futureOnly,
      }}));
    """
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)
    assert result == {
        "originalUnchanged": True,
        "payloadCloned": True,
        "schemaCloned": True,
        "fieldsCloned": True,
        "valuesPreserved": True,
        "runtimeConfigPreserved": True,
        "groupsCloned": True,
        "profilesCloned": True,
        "knownFieldCloned": True,
        "knownTextFieldCloned": True,
        "unknownFieldPreserved": True,
        "knownChoiceValues": ["auto", "modelscope", "huggingface", "offline", "future"],
        "originalChoiceValues": ["auto", "modelscope", "huggingface", "offline", "future"],
        "knownChoicesCloned": True,
        "unknownChoicePreserved": True,
        "textUnknownChoicePreserved": True,
        "machineFieldMetadataPreserved": True,
        "knownGroupCloned": True,
        "unknownGroupPreserved": True,
        "groupMachineMetadataPreserved": True,
        "knownProfileCloned": True,
        "unknownProfilePreserved": True,
        "profileValuesPreserved": True,
        "missingSchemaPreserved": True,
        "futureOnlyPreserved": True,
    }


def test_b1a_keeps_technical_identifiers_as_template_literals() -> None:
    html = ADMIN_HTML.read_text(encoding="utf-8")
    for value in ("AngeVoice Studio", ">Studio<", ">API<", ">Admin<", "ENV Patch", "Raw State", "PBKDF2"):
        assert value in html


def test_final_metadata_controls_are_contained_by_their_grid_cells() -> None:
    css = ADMIN_CSS.read_text(encoding="utf-8")
    match = re.search(
        r"\.config-field input,\s*\.config-field select\s*\{(?P<body>[^}]*)\}",
        css,
    )
    assert match is not None
    declarations = {
        name.strip(): value.strip()
        for name, value in re.findall(r"([\w-]+)\s*:\s*([^;]+);", match.group("body"))
    }
    assert declarations["width"] == "100%"
    assert declarations["min-width"] == "0"
    assert declarations["max-width"] == "100%"
    assert "overflow" not in declarations
    assert "font-size" not in declarations


def test_final_metadata_english_copy_fixups_are_exact() -> None:
    catalog_url = ADMIN_EN_MESSAGES.resolve().as_uri()
    script = f"""
      const {{ messages }} = await import({json.dumps(catalog_url)});
      const keys = {json.dumps(list(FINAL_METADATA_COPY_FIXUPS))};
      console.log(JSON.stringify(Object.fromEntries(keys.map(key => [key, messages[key]]))));
    """
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(completed.stdout) == FINAL_METADATA_COPY_FIXUPS
