"""Runtime resilience, deployment-path, and admin-configuration regressions."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

from kokoro_tts.admin_config_schema import schema_payload
from kokoro_tts.config import TTSConfig
from kokoro_tts.engine_manager import EngineManager
from kokoro_tts.moss.postprocess import compress_long_silence
from kokoro_tts.moss_engine import MossNanoEngine


ROOT = Path(__file__).resolve().parent.parent


def test_production_env_keeps_credentials_and_runtime_config_out_of_outputs():
    env = (ROOT / ".env.prod").read_text(encoding="utf-8")
    assert "ANGEVOICE_API_KEY_FILE=/app/credentials/.angevoice-api-key" in env
    assert "ANGEVOICE_RUNTIME_CONFIG_FILE=/app/config/runtime-config.json" in env
    assert "/app/outputs/.angevoice-api-key" not in env
    assert "/app/outputs/runtime-config.json" not in env


def test_formal_docker_template_enables_killable_moss_workers():
    env = (ROOT / "docker" / "angevoice.env").read_text(encoding="utf-8")
    assert "MOSS_PROCESS_ISOLATION_ENABLED=true" in env
    assert "MOSS_PROCESS_ISOLATION_PROVIDERS=cpu,cuda" in env


def test_admin_schema_separates_product_parameter_groups_and_exposes_zipvoice_controls():
    schema = schema_payload()
    groups = {item["key"] for item in schema["groups"]}
    assert {"kokoro", "moss", "zipvoice", "service", "security"} <= groups
    fields = {item["key"]: item for item in schema["fields"]}
    assert fields["default_speed"]["group"] == "kokoro"
    assert fields["moss_segment_length"]["group"] == "moss"
    assert fields["zipvoice_num_steps"]["group"] == "zipvoice"
    assert fields["zipvoice_prompt_audio_max_seconds"]["default"] == 15.0


def test_zero_moss_silence_limit_disables_compression_instead_of_removing_silence():
    audio = np.concatenate([np.ones(100, dtype=np.float32) * 0.1, np.zeros(200, dtype=np.float32), np.ones(100, dtype=np.float32) * 0.1])
    result, _metrics = compress_long_silence(audio, sample_rate=1000, channels=1, max_silence_ms=0)
    assert result.shape[0] == audio.shape[0]
    assert np.array_equal(result.reshape(-1), audio)


def test_unhealthy_nonisolated_moss_force_unload_never_waits_forever_on_runtime_lock():
    engine = MossNanoEngine(TTSConfig(), execution_provider="cpu", process_isolation=False)
    engine._loaded = True
    engine._unhealthy = True
    acquired = threading.Event()
    release = threading.Event()

    def hold_lock():
        with engine._runtime_lock:
            acquired.set()
            release.wait(timeout=2)

    thread = threading.Thread(target=hold_lock, daemon=True)
    thread.start()
    assert acquired.wait(timeout=1)
    started = time.monotonic()
    engine.unload(force=True)
    elapsed = time.monotonic() - started
    release.set()
    thread.join(timeout=1)
    assert elapsed < 1.0
    assert engine._unhealthy is True


def test_engine_manager_replaces_unhealthy_instance_without_reusing_it():
    cfg = TTSConfig(enabled_models=["kokoro"], default_model="kokoro")
    manager = EngineManager(cfg)
    old = MagicMock()
    old.is_loaded = False
    old.is_healthy = False
    old._unhealthy = True
    fresh = MagicMock()
    fresh.is_loaded = False
    fresh.is_healthy = True
    manager._engines["kokoro"] = old
    manager._create_engine = MagicMock(return_value=fresh)
    result = manager.get_engine("kokoro", load=False)
    assert result is fresh
    manager._create_engine.assert_called_once()


def test_admin_toast_is_visible_horizontal_and_mobile_safe():
    css = (ROOT / "src" / "kokoro_tts" / "static" / "admin.css").read_text(encoding="utf-8")
    html = (ROOT / "src" / "kokoro_tts" / "templates" / "admin.html").read_text(encoding="utf-8")
    assert ".admin-toast {" in css
    assert ".toast {" not in css
    assert "top: 22px;" in css and "right: 22px;" in css
    assert "width: min(420px, calc(100vw - 44px));" in css
    assert "min-width: min(280px, calc(100vw - 44px));" in css
    assert "overflow-wrap: break-word;" in css
    assert "bottom: 22px;" not in css
    assert 'class="admin-toast" id="admin-toast"' in html


def test_idle_unloaded_moss_is_not_misclassified_as_unhealthy():
    engine = MossNanoEngine(TTSConfig(), execution_provider="cpu", process_isolation=False)
    assert engine.is_loaded is False
    assert engine.is_healthy is True
    engine._unhealthy = True
    assert engine.is_healthy is False


def test_all_published_profiles_keep_moss_timeout_recovery_and_startup_grace():
    legacy = (ROOT / "docker" / "legacy-gpu" / "docker-compose.yml").read_text(encoding="utf-8")
    legacy_cuda = (ROOT / "docker" / "legacy-gpu" / "docker-compose.moss-cuda.yml").read_text(encoding="utf-8")
    gpu = (ROOT / "docker" / "gpu" / "docker-compose.yml").read_text(encoding="utf-8")
    fnos = (ROOT / "packaging" / "fnos" / "AngeVoice" / "app" / "docker" / "docker-compose.yaml").read_text(encoding="utf-8")
    assert 'MOSS_PROCESS_ISOLATION_ENABLED: "true"' in legacy
    assert 'MOSS_PROCESS_ISOLATION_PROVIDERS: cpu,cuda' in legacy
    assert 'MOSS_PROCESS_ISOLATION_ENABLED: "true"' in legacy_cuda
    assert 'start_period: 300s' in legacy and 'start_period: 300s' in gpu and 'start_period: 300s' in fnos


def test_dockerfiles_fail_build_on_broken_python_dependency_metadata():
    for rel in ("docker/cpu/Dockerfile", "docker/gpu/Dockerfile", "docker/legacy-gpu/Dockerfile"):
        assert "python3 -m pip check" in (ROOT / rel).read_text(encoding="utf-8")


def test_root_env_example_is_a_comment_only_copy_template():
    env = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    active_assignments = [
        line.strip() for line in env
        if line.strip() and not line.lstrip().startswith("#") and "=" in line
    ]
    assert active_assignments == []


def test_runtime_config_write_uses_private_atomic_target_without_stale_tmp(tmp_path):
    from kokoro_tts.admin_config_schema import save_runtime_config_values

    path = tmp_path / "runtime-config.json"
    cfg = TTSConfig(runtime_config_file=path)
    save_runtime_config_values(cfg, {"cache_max_items": 8})
    assert path.exists()
    assert path.stat().st_mode & 0o777 == 0o600
    assert not list(tmp_path.glob("*.tmp"))
