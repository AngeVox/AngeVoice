from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

import pytest
from fastapi.testclient import TestClient

from kokoro_tts.config import TTSConfig
from kokoro_tts.server import create_app
from kokoro_tts.static_assets import StaticAssetManifest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "src" / "kokoro_tts"
STATIC_ROOT = PACKAGE_ROOT / "static"


def test_manifest_hashes_utf8_text_independently_of_line_endings(tmp_path: Path) -> None:
    lf = tmp_path / "lf.js"
    crlf = tmp_path / "crlf.js"
    lf.write_bytes(b"export const first = 1;\nexport const second = 2;\n")
    crlf.write_bytes(b"export const first = 1;\r\nexport const second = 2;\r\n")
    assert StaticAssetManifest.portable_hash(lf) == StaticAssetManifest.portable_hash(crlf)


def test_manifest_hashes_binary_assets_and_rejects_a_missing_root(tmp_path: Path) -> None:
    binary = tmp_path / "asset.bin"
    payload = b"\xff\x00\xfe\x01"
    binary.write_bytes(payload)
    assert StaticAssetManifest.portable_hash(binary) == hashlib.sha256(payload).hexdigest()[:12]
    with pytest.raises(ValueError):
        StaticAssetManifest(tmp_path / "missing")


def test_manifest_versions_every_javascript_asset_and_rejects_unknown_paths() -> None:
    manifest = StaticAssetManifest(STATIC_ROOT)
    javascript = sorted(path.relative_to(STATIC_ROOT).as_posix() for path in STATIC_ROOT.rglob("*.js"))
    imports = manifest.import_map()["imports"]
    assert set(imports) == {f"/static/{name}" for name in javascript}
    for name in javascript:
        assert imports[f"/static/{name}"] == manifest.url(name)
        assert re.fullmatch(rf"/static/{re.escape(name)}\?h=[0-9a-f]{{12}}", manifest.url(name))

    with pytest.raises(ValueError):
        manifest.url("../templates/index.html")
    with pytest.raises(KeyError):
        manifest.url("missing.js")
    with pytest.raises(TypeError):
        manifest.versions["app.js"] = "000000000000"  # type: ignore[index]


def test_manifest_versions_the_error_presentation_module_by_content() -> None:
    manifest = StaticAssetManifest(STATIC_ROOT)
    name = "studio/error-presentation.js"
    path = STATIC_ROOT / name
    assert manifest.versions[name] == StaticAssetManifest.portable_hash(path)
    assert manifest.import_map()["imports"][f"/static/{name}"] == manifest.url(name)


def test_manifest_versions_the_admin_presentation_module_by_content() -> None:
    manifest = StaticAssetManifest(STATIC_ROOT)
    name = "admin/presentation.js"
    path = STATIC_ROOT / name
    assert manifest.versions[name] == StaticAssetManifest.portable_hash(path)
    assert manifest.import_map()["imports"][f"/static/{name}"] == manifest.url(name)


def test_templates_use_one_manifest_for_css_entries_and_import_maps() -> None:
    for name in ("index.html", "admin.html", "api_docs.html"):
        source = (PACKAGE_ROOT / "templates" / name).read_text(encoding="utf-8")
        assert source.count("asset_import_map_json()") == 1
        assert source.index('type="importmap"') < source.index("asset_url('app.css')")
        assert "?h=" not in source
    for path in STATIC_ROOT.rglob("*.js"):
        assert "?h=" not in path.read_text(encoding="utf-8"), path


def test_templates_use_one_manifest_addressed_svg_favicon() -> None:
    manifest = StaticAssetManifest(STATIC_ROOT)
    favicon = "favicon.svg"
    assert (STATIC_ROOT / favicon).is_file()
    assert manifest.url(favicon).startswith("/static/favicon.svg?h=")
    for name in ("index.html", "admin.html", "api_docs.html"):
        source = (PACKAGE_ROOT / "templates" / name).read_text(encoding="utf-8")
        assert "href=\"data:,\"" not in source
        assert "href=\"/static/favicon.svg" not in source
        assert "{{ asset_url('favicon.svg') }}" in source
        assert 'type="image/svg+xml"' in source


def test_package_data_recursively_includes_future_static_modules() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    patterns = project["tool"]["setuptools"]["package-data"]["kokoro_tts"]
    assert "static/**/*" in patterns


def test_create_app_renders_content_addressed_studio_assets(tmp_path: Path) -> None:
    cfg = TTSConfig(
        model_dir=tmp_path / "models",
        credentials_dir=tmp_path / "credentials",
        api_key_file=tmp_path / "credentials" / ".angevoice-api-key",
        admin_credentials_file=tmp_path / "credentials" / "admin-credentials.json",
        runtime_config_file=tmp_path / "config" / "runtime-config.json",
        enabled_models=["kokoro"],
        default_model="kokoro",
        startup_preload_enabled=False,
        update_check_enabled=False,
    )
    app = create_app(config=cfg)
    manifest = app.state.static_assets
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    html = response.text
    match = re.search(r'<script type="importmap">(?P<payload>.*?)</script>', html)
    assert match
    assert json.loads(match.group("payload")) == manifest.import_map()
    for asset in ("app.css", "common/i18n.js", "security_notice.js", "app.js"):
        assert manifest.url(asset) in html
    assert "{{ asset_url" not in html
