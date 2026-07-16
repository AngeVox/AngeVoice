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


def test_b1a_locale_listener_does_not_expand_rerender_scope() -> None:
    source = ADMIN_JS.read_text(encoding="utf-8")
    listener = re.search(
        r"document\.addEventListener\('angevoice:locale-changed', \(\) => \{(?P<body>.*?)\n\}\);",
        source,
        re.DOTALL,
    )
    assert listener
    body = listener.group("body")
    assert re.findall(r"\b(render[A-Za-z]+)\s*\(", body) == [
        "renderAdminSubnav",
        "renderModels",
        "renderRuntimeConfigNote",
    ]
    for forbidden in ("refresh", "fetch", "renderConfigForms", "renderSecurity", "renderUpdate"):
        assert not re.search(rf"\b{forbidden}\s*\(", body)


def test_b1a_keeps_technical_identifiers_as_template_literals() -> None:
    html = ADMIN_HTML.read_text(encoding="utf-8")
    for value in ("AngeVoice Studio", ">Studio<", ">API<", ">Admin<", "ENV Patch", "Raw State", "PBKDF2"):
        assert value in html
