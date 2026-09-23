"""运行时韧性、部署路径和管理配置回归测试。"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from kokoro_tts.admin_config_schema import schema_payload
from kokoro_tts.config import TTSConfig
from kokoro_tts.engine_manager import EngineManager
from kokoro_tts.moss.postprocess import compress_long_silence
from kokoro_tts.moss_engine import MossNanoEngine


ROOT = Path(__file__).resolve().parent.parent


def test_catalog_snapshot_keeps_identity_and_collects_voices_under_owner_lock():
    manager = EngineManager(TTSConfig(model_idle_timeout_seconds=0, enabled_models=["kokoro", "moss"]))
    engine = MagicMock(is_loaded=False, is_healthy=True)
    engine.metadata.return_value = {"id": "spoof", "backend": "spoof", "voices": []}
    def metadata():
        from concurrent.futures import ThreadPoolExecutor

        def try_lifecycle_lock():
            acquired = manager._lock.acquire(blocking=False)
            if acquired:
                manager._lock.release()
            return acquired

        with ThreadPoolExecutor(1) as pool:
            assert pool.submit(try_lifecycle_lock).result(timeout=2) is False
        return {"id": "spoof", "backend": "spoof", "voices": []}

    engine.metadata.side_effect = metadata
    engine.get_voices.return_value = "voice-one"
    manager._create_engine = MagicMock(return_value=engine)
    try:
        snapshot = manager.catalog_snapshot("moss")
        assert snapshot["id"] == "moss"
        assert snapshot["backend"] != "spoof"
        assert snapshot["voices"] == ["voice-one"]
        assert snapshot["current"] is False
        engine.load.assert_not_called()
        engine.metadata.assert_called_once()
    finally:
        manager.stop_idle_timer()


@pytest.mark.parametrize("active", [0, 1])
@pytest.mark.parametrize("load", [False, True])
def test_manager_provider_replacement_preserves_busy_and_load_false(active, load):
    from fastapi import HTTPException
    manager = EngineManager(TTSConfig(model_idle_timeout_seconds=0, enabled_models=["kokoro", "moss"]))
    old = MagicMock(is_loaded=True, is_healthy=True, requested_provider="cpu")
    fresh = MagicMock(is_loaded=False, is_healthy=True, requested_provider="cuda")
    manager._engines["moss"] = old
    manager._active_counts["moss"] = active
    manager._create_engine = MagicMock(return_value=fresh)
    try:
        if active:
            with pytest.raises(HTTPException) as caught:
                manager.get_engine("moss", load=load, provider_hint="cuda")
            assert caught.value.status_code == 409
            assert manager._engines["moss"] is old
            old.unload.assert_not_called()
            manager._create_engine.assert_not_called()
        else:
            assert manager.get_engine("moss", load=load, provider_hint="cuda") is fresh
            old.unload.assert_called_once_with(force=False)
            manager._create_engine.assert_called_once_with("moss", provider_hint="cuda")
            assert fresh.load.call_count == int(load)
    finally:
        manager.stop_idle_timer()


@pytest.mark.parametrize("method", ["unload_model", "drop_model"])
@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("fails", [False, True])
def test_manager_unload_invokes_once_and_preserves_failure_state(method, legacy, fails):
    manager = EngineManager(TTSConfig(model_idle_timeout_seconds=0))
    calls = []

    def unload(*, force=False):
        calls.append(force)
        if fails:
            raise TypeError("runtime failure, not an incompatible signature")

    def old_unload():
        unload()

    engine = MagicMock(is_loaded=True, is_healthy=True)
    engine.unload = old_unload if legacy else unload
    manager._engines["kokoro"] = engine
    manager._active_counts["kokoro"] = 2
    try:
        assert getattr(manager, method)("kokoro", force=True) is (not fails)
        assert calls == [not legacy]
        assert manager._active_count("kokoro") == (2 if fails else 0)
        assert ("kokoro" in manager._engines) == (fails or method == "unload_model")
        assert ("kokoro" in manager._pending_rebuild) == (fails and method == "drop_model")
    finally:
        manager.stop_idle_timer()


@pytest.mark.parametrize("cleanup", ["force", "legacy", "fails", "legacy-fails", "type-error"])
def test_manager_failed_load_preserves_error_clears_state_and_retries(cleanup):
    manager = EngineManager(TTSConfig(model_idle_timeout_seconds=0, enabled_models=["kokoro"]))
    original = RuntimeError("synthetic load failure")
    failed = MagicMock(is_loaded=False, is_healthy=True)
    failed.load.side_effect = original
    calls = []

    def legacy_unload():
        calls.append("legacy")
        if cleanup == "legacy-fails":
            raise OSError("synthetic cleanup failure")

    def force_unload(*, force):
        calls.append(force)
        if cleanup == "type-error":
            raise TypeError("runtime cleanup failure")
        if cleanup == "fails":
            raise OSError("synthetic cleanup failure")

    failed.unload = legacy_unload if cleanup.startswith("legacy") else force_unload
    fresh = MagicMock(is_loaded=False, is_healthy=True)
    fresh.load.side_effect = lambda: setattr(fresh, "is_loaded", True)
    manager._create_engine = MagicMock(side_effect=[failed, fresh])
    try:
        with pytest.raises(RuntimeError) as caught:
            manager.get_engine("kokoro")
        assert caught.value is original
        assert "kokoro" not in manager._engines
        assert manager._active_count("kokoro") == 0
        assert "kokoro" not in manager._last_used
        assert calls == (["legacy"] if cleanup.startswith("legacy") else [True])
        assert manager.get_engine("kokoro") is fresh
        assert manager._engines["kokoro"] is fresh
        assert "kokoro" in manager._last_used
        fresh.load.assert_called_once()
    finally:
        manager.stop_idle_timer()


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
    assert {"kokoro", "moss", "zipvoice", "service", "audio", "security"} <= groups
    fields = {item["key"]: item for item in schema["fields"]}
    assert fields["default_speed"]["group"] == "kokoro"
    assert fields["moss_segment_length"]["group"] == "moss"
    assert fields["zipvoice_num_steps"]["group"] == "zipvoice"
    assert fields["zipvoice_prompt_audio_max_seconds"]["default"] == 15.0
    assert fields["websocket_max_connections"]["default"] == 16
    assert fields["websocket_max_message_bytes"]["default"] == 33554432
    assert fields["rate_limit_qps"]["default"] == 10.0
    assert fields["max_queue_length"]["default"] == 50
    assert fields["ffmpeg_enabled"]["group"] == "audio"
    assert fields["ffmpeg_enabled"]["type"] == "bool"
    assert fields["ffmpeg_enabled"]["advanced"] is False
    assert fields["ffmpeg_binary"]["group"] == "audio"
    assert fields["mp3_bitrate"]["group"] == "audio"
    assert fields["audio_opus_bitrate"]["group"] == "audio"
    assert fields["audio_aac_bitrate"]["group"] == "audio"


def test_zero_moss_silence_limit_disables_compression_instead_of_removing_silence():
    audio = np.concatenate([np.ones(100, dtype=np.float32) * 0.1, np.zeros(200, dtype=np.float32), np.ones(100, dtype=np.float32) * 0.1])
    result, _metrics = compress_long_silence(audio, sample_rate=1000, channels=1, max_silence_ms=0)
    assert result.shape[0] == audio.shape[0]
    assert np.array_equal(result.reshape(-1), audio)


@pytest.mark.parametrize("transition", ["rebuild", "force_unload"])
def test_moss_executor_transition_cancels_pending_work_without_killing_active_work(transition):
    engine = MossNanoEngine(TTSConfig(), execution_provider="cpu", process_isolation=False)
    entered = threading.Event()
    release = threading.Event()
    pending_ran = threading.Event()
    old = engine._executor

    def active():
        with engine._runtime_lock:
            entered.set()
            return release.wait(5)

    running = old.submit(active)
    try:
        assert entered.wait(3)
        pending = old.submit(pending_ran.set)
        if transition == "force_unload":
            engine.unload(force=True)
            assert not engine.is_healthy
        else:
            engine._rebuild_executor()
        assert pending.cancelled()
        assert not running.done()
        assert engine._executor.submit(lambda: "new executor").result(timeout=3) == "new executor"
        release.set()
        assert running.result(timeout=3) is True
        old.shutdown(wait=True)
        assert not pending_ran.is_set()
    finally:
        release.set()
        old.shutdown(wait=True)
        engine._executor.shutdown(wait=True)


def test_current_snapshot_selects_model_inside_lifecycle_lock(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    manager = EngineManager(TTSConfig(model_idle_timeout_seconds=0))
    gate = threading.RLock()
    waiting = threading.Event()
    gate.acquire()

    class ObservedLock:
        def __enter__(self):
            waiting.set()
            gate.acquire()

        def __exit__(self, *args):
            gate.release()

    monkeypatch.setattr(manager, "_lock", ObservedLock())
    monkeypatch.setattr(manager, "_runtime_available", lambda spec: True)
    monkeypatch.setattr(manager, "_create_engine", lambda *a, **kw: pytest.fail("snapshot must not construct an engine"))
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        result = pool.submit(manager.current_snapshot, include_runtime_metadata=False)
        assert waiting.wait(3)
        # Reproduce a lifecycle transition while the reader is waiting for the lock.
        manager._current_model_id = "moss"
        gate.release()
        snapshot = result.result(timeout=3)
        assert snapshot["id"] == "moss"
        assert snapshot["current"] is True
        assert manager._engines == {}
    finally:
        # Only the controlling thread acquires the initial gate.
        try:
            gate.release()
        except RuntimeError:
            pass
        pool.shutdown(wait=True)
        manager.stop_idle_timer()


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
    assert "top: 132px;" in css and "right: 22px;" in css
    assert "z-index: 1300;" in css
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
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600
    assert not list(tmp_path.glob("*.tmp"))


def test_formal_docker_template_enables_safe_entry_guardrails_by_default():
    env = (ROOT / "docker" / "angevoice.env").read_text(encoding="utf-8")
    fnos_env = (ROOT / "packaging" / "fnos" / "AngeVoice" / "app" / "docker" / "angevoice.env").read_text(encoding="utf-8")
    for content in (env, fnos_env):
        assert "KOKORO_RATE_LIMIT_QPS=10" in content
        assert "KOKORO_RATE_LIMIT_BURST=20" in content
        assert "KOKORO_MAX_QUEUE_LENGTH=50" in content
        assert "KOKORO_WS_MAX_CONNECTIONS=16" in content
        assert "KOKORO_WS_MAX_MESSAGE_BYTES=33554432" in content


def test_idle_unload_restart_hook_exits_only_when_service_is_fully_idle(tmp_path):
    from kokoro_tts.service_state import ServiceState

    cfg = TTSConfig(
        model_idle_timeout_seconds=0,
        restart_after_idle_unload_enabled=True,
        restart_after_idle_unload_delay_seconds=0.01,
        restart_after_idle_unload_cooldown_seconds=0,
        restart_after_idle_unload_exit_code=75,
        runtime_config_file=tmp_path / "runtime-config.json",
    )
    state = ServiceState(cfg)
    exited = threading.Event()
    exit_codes: list[int] = []

    def fake_exit(code: int) -> None:
        exit_codes.append(code)
        exited.set()

    state._process_exit = fake_exit
    state.handle_idle_unload_completed(["moss"])
    assert exited.wait(timeout=1)
    assert exit_codes == [75]


def test_manual_resource_release_can_schedule_container_restart(tmp_path):
    from kokoro_tts.service_state import ServiceState

    cfg = TTSConfig(
        model_idle_timeout_seconds=0,
        restart_after_idle_unload_enabled=True,
        restart_after_idle_unload_delay_seconds=0.05,
        restart_after_idle_unload_cooldown_seconds=0,
        runtime_config_file=tmp_path / "runtime-config.json",
    )
    state = ServiceState(cfg)
    state.model_manager.unload_inactive = MagicMock(return_value=["moss"])
    exited = threading.Event()
    state._process_exit = lambda code: exited.set()

    result = state.release_resources(unload_models=True)

    assert result["unloaded_models"] == ["moss"]
    assert result["restart"]["scheduled"] is True
    assert result["restart"]["reason"] == "manual"
    assert result["after"]["restart"]["scheduled"] is True
    assert exited.wait(timeout=1)


def test_manual_resource_release_does_not_restart_while_request_is_active(tmp_path):
    from kokoro_tts.service_state import ServiceState

    cfg = TTSConfig(
        model_idle_timeout_seconds=0,
        restart_after_idle_unload_enabled=True,
        restart_after_idle_unload_delay_seconds=0.01,
        restart_after_idle_unload_cooldown_seconds=0,
        runtime_config_file=tmp_path / "runtime-config.json",
    )
    state = ServiceState(cfg)
    state.model_manager.unload_inactive = MagicMock(return_value=["moss"])
    state.mark_request("active", "running")
    exited = threading.Event()
    state._process_exit = lambda code: exited.set()

    result = state.release_resources(unload_models=True)
    time.sleep(0.05)

    assert result["restart"]["scheduled"] is False
    assert exited.is_set() is False


def test_health_reports_restarting_when_unload_restart_is_scheduled(tmp_path):
    from fastapi.testclient import TestClient
    from kokoro_tts.server import create_app

    cfg = TTSConfig(
        model_idle_timeout_seconds=0,
        restart_after_idle_unload_enabled=True,
        restart_after_idle_unload_delay_seconds=60,
        runtime_config_file=tmp_path / "runtime-config.json",
    )
    app = create_app(config=cfg)
    state = app.state.angevoice
    state.handle_model_unload_completed(["moss"], reason="manual")

    payload = TestClient(app).get("/health").json()

    assert payload["status"] == "restarting"
    assert payload["restart"]["scheduled"] is True
    assert payload["restart"]["reason"] == "manual"


def test_idle_unload_restart_hook_is_cancelled_when_new_connection_arrives(tmp_path):
    from kokoro_tts.service_state import ServiceState

    cfg = TTSConfig(
        model_idle_timeout_seconds=0,
        restart_after_idle_unload_enabled=True,
        restart_after_idle_unload_delay_seconds=0.02,
        restart_after_idle_unload_cooldown_seconds=0,
        runtime_config_file=tmp_path / "runtime-config.json",
    )
    state = ServiceState(cfg)
    exited = threading.Event()
    state._process_exit = lambda code: exited.set()
    state._websocket_connections = 1
    state.handle_idle_unload_completed(["moss"])
    time.sleep(0.08)
    assert not exited.is_set()
    assert state.idle_restart_snapshot()["scheduled"] is False


def test_admin_schema_exposes_idle_unload_cleanup_switch():
    schema = schema_payload()
    fields = {item["key"]: item for item in schema["fields"]}
    field = fields["restart_after_idle_unload_enabled"]
    assert field["group"] == "service"
    assert field["type"] == "bool"
    assert field["default"] is False
    assert "Docker" in field["help"]
    assert fields["restart_after_idle_unload_delay_seconds"]["advanced"] is True


def test_resource_snapshot_reads_requests_under_registry_lock(tmp_path):
    from kokoro_tts.service_state import ServiceState

    state = ServiceState(TTSConfig(model_dir=tmp_path, model_idle_timeout_seconds=0))

    class GuardedRequests(dict):
        def values(self):
            assert state.request_lock.locked(), "共享请求记录必须在锁内读取"
            return super().values()

    state.active_requests = GuardedRequests({
        "active": {"id": "active", "status": "running"},
        "finished": {"id": "finished", "status": "done"},
    })
    assert state.resource_snapshot()["active_requests"] == 1


def test_admin_status_request_records_are_detached_and_limited(tmp_path):
    import asyncio
    from kokoro_tts.routes.admin import create_admin_router
    from kokoro_tts.service_state import ServiceState

    state = ServiceState(TTSConfig(model_dir=tmp_path, model_idle_timeout_seconds=0))
    for index in range(55):
        state.mark_request(str(index), "running", updated_at=float(index))
    router = create_admin_router(state)
    endpoint = next(route.endpoint for route in router.routes if route.path == "/admin/api/status")
    payload = asyncio.run(endpoint())
    records = payload["active_requests"]
    assert len(records) == 50
    assert [item["id"] for item in records] == [str(index) for index in range(54, 4, -1)]
    state.mark_request("54", "done")
    assert records[0]["status"] == "running"
    records[1]["status"] = "cancelled"
    assert state.request_info("53")["status"] == "running"
