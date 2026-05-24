import json
import base64
from pathlib import Path

import pytest

from kokoro_tts.admin_config_schema import (
    apply_admin_config_values,
    export_env_patch,
    load_runtime_config,
    profile_values,
    runtime_config_path,
    save_runtime_config_values,
    validate_admin_config_values,
)
from kokoro_tts.config import TTSConfig
from kokoro_tts.routes.admin_models import AdminConfigPatch


def test_admin_config_rejects_unknown_field():
    with pytest.raises(KeyError):
        validate_admin_config_values({"not_a_real_field": 1})
    with pytest.raises(Exception):
        AdminConfigPatch(not_a_real_field=1)


def test_admin_profile_values_are_valid_and_apply():
    cfg = TTSConfig()
    values = profile_values("long_narration")
    changed, restart_required, rebuild_moss = apply_admin_config_values(cfg, values)
    assert "moss_segment_length" in changed
    assert restart_required == []
    assert rebuild_moss is True
    assert cfg.moss_segment_length == 260
    assert cfg.moss_stream_chunk_seconds == 0.55


def test_runtime_config_persists_only_changed_values(tmp_path):
    cfg = TTSConfig(runtime_config_file=tmp_path / "runtime-config.json")
    save_runtime_config_values(cfg, {"moss_segment_length": 280, "moss_audio_polish_enabled": False})

    payload = json.loads(runtime_config_path(cfg).read_text(encoding="utf-8"))
    assert payload["values"] == {"moss_segment_length": 280, "moss_audio_polish_enabled": False}

    cfg2 = TTSConfig(runtime_config_file=tmp_path / "runtime-config.json")
    loaded = load_runtime_config(cfg2)
    assert set(loaded) == {"moss_segment_length", "moss_audio_polish_enabled"}
    assert cfg2.moss_segment_length == 280
    assert cfg2.moss_audio_polish_enabled is False


def test_runtime_config_load_ignores_removed_legacy_keys(tmp_path):
    cfg_path = tmp_path / "runtime-config.json"
    cfg_path.write_text(
        json.dumps(
            {
                "values": {
                    "public_status_endpoints": False,
                    "admin_allow_api_key": True,
                }
            }
        ),
        encoding="utf-8",
    )

    cfg = TTSConfig(runtime_config_file=cfg_path, public_status_endpoints=True)
    loaded = load_runtime_config(cfg)
    assert loaded == ["public_status_endpoints"]
    assert cfg.public_status_endpoints is False


def test_export_env_patch_uses_schema_env_names():
    env = export_env_patch({"moss_segment_length": 120, "moss_audio_polish_enabled": True}, only=["moss_segment_length", "moss_audio_polish_enabled"])
    assert "MOSS_SEGMENT_LENGTH=120" in env
    assert "MOSS_AUDIO_POLISH_ENABLED=true" in env


@pytest.mark.skipif(pytest.importorskip("fastapi", reason="fastapi not installed") is None, reason="fastapi not installed")
def test_admin_config_routes_expose_schema_and_reject_unknown(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from kokoro_tts.server import create_app

    monkeypatch.setenv("ANGEVOICE_ADMIN_PASSWORD", "secret")
    cfg = TTSConfig(
        model_dir=Path("/nonexistent"),
        enabled_models=["kokoro", "moss-nano-cpu"],
        default_model="kokoro",
        admin_enabled=True,
        runtime_config_file=tmp_path / "runtime-config.json",
    )
    client = TestClient(create_app(config=cfg))
    headers = {"Authorization": "Basic " + base64.b64encode(b"admin:secret").decode("ascii")}

    schema = client.get("/admin/api/config/schema", headers=headers)
    assert schema.status_code == 200
    assert any(field["key"] == "moss_segment_length" for field in schema.json()["fields"])

    result = client.post("/admin/api/config/profile", headers=headers, json={"profile": "long_narration"})
    assert result.status_code == 200
    assert "moss_segment_length" in result.json()["changed"]
    assert (tmp_path / "runtime-config.json").exists()

    rejected = client.patch("/admin/api/config", headers=headers, json={"not_real": 1})
    assert rejected.status_code == 422


def test_nas_stable_profile_is_actually_safe():
    values = profile_values("nas_stable")
    assert values["moss_segment_length"] == 120
    assert values["moss_voice_clone_max_text_tokens"] == 56
    assert values["moss_max_new_frames"] == 320
    assert values["moss_stream_queue_max_items"] == 8
    assert values["moss_vram_guard_enabled"] is True
    assert values["moss_apply_angevoice_rules"] == "auto"
    assert values["moss_vram_snapshot_ttl_seconds"] == 10.0


def test_runtime_config_info_and_delete(tmp_path):
    from kokoro_tts.admin_config_schema import delete_runtime_config, runtime_config_info

    cfg = TTSConfig(runtime_config_file=tmp_path / "runtime-config.json")
    assert runtime_config_info(cfg)["exists"] is False
    save_runtime_config_values(cfg, {"moss_segment_length": 120})
    info = runtime_config_info(cfg)
    assert info["exists"] is True
    assert info["field_count"] == 1
    assert delete_runtime_config(cfg) is True
    assert runtime_config_info(cfg)["exists"] is False


def test_admin_runtime_guards_clamp_risky_combinations(tmp_path):
    from kokoro_tts.routes.admin_runtime import apply_config_patch

    cfg = TTSConfig(runtime_config_file=tmp_path / "runtime-config.json")
    patch = AdminConfigPatch(
        moss_vram_safe_free_mb=1000,
        moss_vram_critical_free_mb=1200,
        moss_stream_chunk_seconds=0.6,
        moss_stream_prebuffer_seconds=0.2,
        moss_segment_length=120,
        moss_voice_clone_max_text_tokens=200,
        moss_output_target_peak=0.8,
        moss_output_gain=2.0,
    )
    changed, _, _ = apply_config_patch(cfg, patch)
    assert "moss_vram_critical_free_mb" in changed
    assert "moss_stream_prebuffer_seconds" in changed
    assert "moss_voice_clone_max_text_tokens" in changed
    assert "moss_output_gain" in changed
    assert cfg.moss_vram_critical_free_mb == 900
    assert cfg.moss_stream_prebuffer_seconds == 0.6
    assert cfg.moss_voice_clone_max_text_tokens == 60
    assert cfg.moss_output_gain == pytest.approx(0.96)
