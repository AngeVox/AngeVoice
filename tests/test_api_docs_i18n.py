from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from kokoro_tts.config import TTSConfig
from kokoro_tts.server import create_app


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "kokoro_tts"
ANCHORS = {"quick", "models", "openai", "moss-clone", "moss-http", "moss-ws", "zipvoice-http", "server-default", "errors"}


def _page(tmp_path, api_key: str | None = None) -> str:
    app = create_app(config=TTSConfig(model_dir=tmp_path / "models", credentials_dir=tmp_path / "credentials", api_key=api_key, startup_preload_enabled=False, update_check_enabled=False))
    with TestClient(app) as client:
        response = client.get("/api-docs")
    assert response.status_code == 200
    return response.text


def test_api_docs_preserves_route_bootstrap_and_module_shell(tmp_path):
    html = _page(tmp_path, "secret-not-in-bootstrap")
    payload = json.loads(re.search(r'id="angevoice-docs-bootstrap"[^>]*>([^<]+)</script>', html).group(1))
    assert {"authRequired", "mossPromptUploadMaxBytes", "mossPromptAudioMaxSeconds"} <= set(payload)
    assert payload["authRequired"] is True
    assert "secret-not-in-bootstrap" not in html
    assert "asset_url('common/i18n.js')" in (PACKAGE / "templates/api_docs.html").read_text(encoding="utf-8")
    assert "asset_url('docs/docs.js')" in (PACKAGE / "templates/api_docs.html").read_text(encoding="utf-8")


def test_docs_schema_has_exact_anchors_copy_recipes_and_catalog_keys():
    script = f"""import {{ DOCS_CONTENT, collectDocsTranslationKeys }} from {json.dumps((PACKAGE / 'static/docs/docs-content.js').as_uri())};
const copies = DOCS_CONTENT.sections.flatMap(s => s.blocks).filter(b => b.type === 'codeBlock').map(b => b.copyId);
console.log(JSON.stringify({{anchors:DOCS_CONTENT.sections.map(s=>s.id),copies,keys:[...collectDocsTranslationKeys()].sort()}}));"""
    result = json.loads(subprocess.run(["node", "--input-type=module", "--eval", script], check=True, capture_output=True, text=True).stdout)
    assert set(result["anchors"]) == ANCHORS
    assert len(result["copies"]) == len(set(result["copies"])) == 14
    for locale in ("zh-cn", "en"):
        source = (PACKAGE / f"static/locale/docs/messages.{locale}.js").read_text(encoding="utf-8")
        for key in result["keys"]:
            assert f"'{key}':" in source
