"""CPU 部署安全、持久化与校验入口测试。"""

from __future__ import annotations

import base64
import json
import os
import zipfile
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from kokoro_tts.admin_config_schema import load_runtime_config, profile_values
from kokoro_tts.admin_credentials import AdminCredentialStore
from kokoro_tts.config import TTSConfig
from kokoro_tts.config_api_key import load_or_generate_api_key
from kokoro_tts.server import create_app
from kokoro_tts.zipvoice.profiles import ZipVoiceProfileStore


def basic(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def fake_engine() -> MagicMock:
    engine = MagicMock()
    engine.is_loaded = True
    engine.is_healthy = True
    engine.get_voices.return_value = ["zm_010"]
    engine.default_voice = "zm_010"
    engine.metadata.return_value = {"id": "kokoro", "loaded": True, "voice_clone_supported": False}
    return engine


def test_persisted_admin_credentials_store_hash_not_plaintext(tmp_path):
    cfg = TTSConfig(admin_credentials_file=tmp_path / "credentials" / "admin-credentials.json")
    store = AdminCredentialStore(cfg)
    status = store.set_credentials("operator", "StrongPass-2026")
    raw = cfg.admin_credentials_file.read_text(encoding="utf-8")
    assert status["persisted"] is True
    assert "StrongPass-2026" not in raw
    assert "pbkdf2_hmac_sha256" in raw
    assert store.verify("operator", "StrongPass-2026") is True
    assert store.verify("operator", "wrong-password") is False
    if os.name != "nt":
        assert (cfg.admin_credentials_file.stat().st_mode & 0o777) == 0o600


def test_api_key_and_runtime_config_migrate_from_legacy_outputs(tmp_path):
    outputs = tmp_path / "outputs"; outputs.mkdir()
    credentials = tmp_path / "credentials"
    config_dir = tmp_path / "config"
    legacy_key = "av_legacy-token"
    (outputs / ".angevoice-api-key").write_text(legacy_key + "\n", encoding="utf-8")
    (outputs / "runtime-config.json").write_text(json.dumps({"values": {"cache_max_items": 12}}), encoding="utf-8")
    cfg = TTSConfig(output_dir=outputs, api_key_file=credentials / ".angevoice-api-key", runtime_config_file=config_dir / "runtime-config.json")
    assert load_or_generate_api_key(cfg) == legacy_key
    assert (credentials / ".angevoice-api-key").read_text(encoding="utf-8").strip() == legacy_key
    assert load_runtime_config(cfg) == ["cache_max_items"]
    assert cfg.cache_max_items == 12
    migrated = json.loads((config_dir / "runtime-config.json").read_text(encoding="utf-8"))
    assert Path(migrated["migrated_from"]).as_posix().endswith("outputs/runtime-config.json")


def test_low_memory_deep_sleep_profile_is_explicit_profile():
    values = profile_values("nas_deep_sleep_cpu")
    assert values["model_idle_timeout_seconds"] == 180.0
    assert values["model_idle_unload_current"] is True
    assert values["cache_max_bytes"] == 134217728
    assert values["cache_skip_text_over_chars"] == 400
    assert values["max_concurrent_requests"] == 1


def test_voice_profile_metadata_and_integrity_verification(tmp_path):
    cfg = TTSConfig(zipvoice_profiles_dir=tmp_path / "prompts" / "zipvoice")
    store = ZipVoiceProfileStore(cfg)
    store.save(voice_id="profile_a", prompt_text="参考文字", audio_bytes=b"RIFF-profile-a", name="原名称")
    changed = store.update_metadata("profile_a", name="发布音色", description="正式候选", tags=["nas", "cpu"])
    assert changed["name"] == "发布音色"
    assert changed["tags"] == ["nas", "cpu"]
    assert store.verify("profile_a")["ready"] is True
    (cfg.zipvoice_profiles_dir / "profile_a" / "reference.wav").write_bytes(b"modified")
    result = store.verify("profile_a")
    assert result["ready"] is False
    assert "reference_audio_sha256 mismatch" in result["profiles"][0]["issues"]


def test_admin_can_persist_new_credentials_and_download_redacted_diagnostics(monkeypatch, tmp_path):
    monkeypatch.setenv("ANGEVOICE_ADMIN_PASSWORD", "Bootstrap-Pass-2026")
    cfg = TTSConfig(
        admin_enabled=True,
        enabled_models=["kokoro"],
        default_model="kokoro",
        output_dir=tmp_path / "outputs",
        credentials_dir=tmp_path / "credentials",
        admin_credentials_file=tmp_path / "credentials" / "admin-credentials.json",
        api_key_file=tmp_path / "credentials" / ".angevoice-api-key",
        runtime_config_file=tmp_path / "config" / "runtime-config.json",
        zipvoice_profiles_dir=tmp_path / "prompts" / "zipvoice",
        zipvoice_model_root=tmp_path / "models" / "zipvoice",
        model_idle_timeout_seconds=0,
    )
    app = create_app(config=cfg, engine=fake_engine())
    try:
        with TestClient(app) as client:
            response = client.put(
                "/admin/api/security/credentials",
                headers=basic("admin", "Bootstrap-Pass-2026"),
                json={"username": "operator", "password": "New-Strong-Pass-2026"},
            )
            assert response.status_code == 200
            assert response.json()["admin_credentials"]["persisted"] is True
            assert client.get("/admin/api/security", headers=basic("admin", "Bootstrap-Pass-2026")).status_code == 401
            status = client.get("/admin/api/security", headers=basic("operator", "New-Strong-Pass-2026"))
            assert status.status_code == 200
            assert status.json()["admin_auth_source"] == "persisted_hash"
            bundle = client.get("/admin/api/diagnostics/bundle", headers=basic("operator", "New-Strong-Pass-2026"))
            assert bundle.status_code == 200
            with zipfile.ZipFile(BytesIO(bundle.content)) as archive:
                names = set(archive.namelist())
                all_bytes = b"".join(archive.read(name) for name in names)
            assert "security/security-redacted.json" in names
            assert b"New-Strong-Pass-2026" not in all_bytes
            assert b"Bootstrap-Pass-2026" not in all_bytes
    finally:
        app.state.angevoice.model_manager.stop_idle_timer()




def test_fnos_package_uses_verified_compose_profile_template_for_v26601():
    root = Path(__file__).resolve().parents[1]
    guide = (root / "docs/FNOS_FPK.md").read_text(encoding="utf-8")
    manifest = (root / "packaging/fnos/AngeVoice/manifest").read_text(encoding="utf-8")
    compose = (root / "packaging/fnos/AngeVoice/app/docker/docker-compose.yaml").read_text(encoding="utf-8")
    install_callback = (root / "packaging/fnos/AngeVoice/cmd/install_callback").read_text(encoding="utf-8")
    assert "单一 Compose 文件 + 三个互斥 profile service" in guide
    assert "COMPOSE_PROFILES" in guide
    assert "version               = 2.6.610" in manifest
    assert compose.count("profiles:") == 3
    assert "angevoice-cpu:" in compose and "angevoice-gpu:" in compose and "angevoice-legacy-gpu:" in compose
    assert "maxblack777/angevoice-gpu:latest" in compose
    assert "${wizard_admin_password:-admin123}" in compose
    assert "ZIPVOICE_PROCESS_ISOLATION_ENABLED" in compose
    assert "ANGEVOICE_STARTUP_PRELOAD_ENABLED" in compose
    assert "COMPOSE_PROFILES" in install_callback
    assert "wizard_run_mode" not in install_callback
    assert "wizard_container_runtime" not in install_callback
    assert "${TRIM_PKGVAR}/cmd/_mode_env.sh" in install_callback
    assert "source \"${TRIM_PKGVAR}/cmd/_mode_env.sh\"" not in install_callback
    fnos_env = (root / "packaging/fnos/AngeVoice/app/docker/angevoice.env").read_text(encoding="utf-8")
    assert "KOKORO_PROCESS_ISOLATION_ENABLED=true" in fnos_env
    assert "MOSS_PROCESS_ISOLATION_ENABLED=true" in fnos_env
    assert "ZIPVOICE_PROCESS_ISOLATION_ENABLED=true" in fnos_env
    assert "ANGEVOICE_STARTUP_PRELOAD_ENABLED=false" in fnos_env
