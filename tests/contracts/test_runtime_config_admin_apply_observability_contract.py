"""P2G-B runtime-config, Admin apply, and observability contracts.

The tests are hermetic.  Runtime files live under ``tmp_path``; environment
application, Uvicorn, HTTP clients, processes, models, networks, credentials,
and service/container restart paths are never invoked.

Contract classifications:

* load order, envelope, atomic replace, merge, and current-worker dispatch:
  BEHAVIOR/OWNERSHIP CONTRACT;
* fcntl and concrete Admin/request owners: STATIC/BEHAVIOR CONTRACT;
* mutation-before-save, Windows process-local locking, stale workers, missing
  convergence observability, and UI wording: CURRENT-BEHAVIOR
  CHARACTERIZATION (not design endorsement).
"""

from __future__ import annotations

import ast
import asyncio
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from kokoro_tts import config as config_module
from kokoro_tts.admin_config import schema as admin_schema
from kokoro_tts.config import TTSConfig
from kokoro_tts.routes import admin as admin_routes
from kokoro_tts.routes import admin_runtime
from kokoro_tts.routes.admin_models import AdminConfigPatch


pytestmark = pytest.mark.contract

PACKAGE_ROOT = Path(__file__).parents[2] / "src" / "kokoro_tts"
MISSING_CONVERGENCE_FIELDS = {
    "runtime_config_mtime",
    "runtime_config_hash",
    "config_generation",
    "applied_generation",
    "worker_id",
    "all_workers_applied",
    "other_worker_state",
    "child_config_identity",
    "restart_completed",
}
RESTART_FIELDS = {
    "max_concurrent_requests",
    "startup_preload_enabled",
    "startup_preload_model",
    "moss_hf_repo",
    "rate_limit_qps",
    "rate_limit_burst",
    "max_queue_length",
    "websocket_max_connections",
    "websocket_max_message_bytes",
    "trust_proxy_headers",
}
REBUILD_FIELDS = {
    "kokoro_process_isolation_enabled",
    "zipvoice_process_isolation_enabled",
    "moss_segment_length",
    "moss_voice_clone_max_text_tokens",
    "moss_max_new_frames",
    "moss_prompt_audio_max_seconds",
    "moss_quality_gate_enabled",
    "moss_process_isolation_enabled",
}


def _module_tree(relative: str) -> ast.Module:
    return ast.parse(
        (PACKAGE_ROOT / relative).read_text(encoding="utf-8"),
        filename=relative,
    )


def _definition(
    tree: ast.AST, name: str
) -> ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef:
    return next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and node.name == name
    )


def _call_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for call in (item for item in ast.walk(node) if isinstance(item, ast.Call)):
        if isinstance(call.func, ast.Name):
            names.add(call.func.id)
        elif isinstance(call.func, ast.Attribute):
            names.add(call.func.attr)
    return names


def _synthetic_config(tmp_path: Path, *, value: int = 10) -> TTSConfig:
    """Avoid the environment-backed default model-directory factory."""

    return TTSConfig(
        model_dir=tmp_path / "models",
        output_dir=tmp_path / "outputs",
        runtime_config_file=tmp_path / "runtime-config.json",
        cache_max_items=value,
    )


def _write_runtime(path: Path, values: dict[str, object], *, envelope: bool = True):
    payload: dict[str, object]
    if envelope:
        payload = {"version": 1, "updated_at": 123, "values": values}
    else:
        payload = values
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def _admin_endpoint(router, path: str, method: str):
    return next(
        route.endpoint
        for route in router.routes
        if route.path == path and method in route.methods
    )


def _build_admin_router(monkeypatch, cfg, manager):
    """Build routes only; external services are replaced before construction."""

    async def fake_verify_admin():
        return None

    monkeypatch.setattr(
        admin_routes, "make_verify_admin", lambda _cfg: fake_verify_admin
    )
    monkeypatch.setattr(admin_routes, "ModelAssetService", lambda _cfg: object())
    monkeypatch.setattr(admin_routes, "UpdateChecker", lambda _cfg: object())
    state = SimpleNamespace(
        cfg=cfg,
        model_manager=manager,
        cache_clear=lambda: manager.events.append(("cache_clear",)),
    )
    return admin_routes.create_admin_router(state)


class TestConfigLoadPriority:
    def test_load_order_and_explicit_runtime_path_limitation(self, monkeypatch, tmp_path):
        """BEHAVIOR CONTRACT without reading process environment or real files."""

        events: list[object] = []
        initially_selected = tmp_path / "selected-before-explicit.json"
        explicit_path = tmp_path / "explicit-too-late-for-this-load.json"

        class FakeConfig:
            def __init__(self):
                events.append("defaults")
                self.cache_max_items = 1
                self.output_dir = str(tmp_path / "outputs")
                self.credentials_dir = str(tmp_path / "credentials")
                self.api_key_file = str(tmp_path / "credentials" / "api-key")
                self.admin_credentials_file = str(
                    tmp_path / "credentials" / "admin.json"
                )
                self.runtime_config_file = initially_selected
                self.model_dir = str(tmp_path / "models")
                self.moss_model_dir = None
                self.moss_audio_tokenizer_model_dir = None
                self.moss_repo_path = None
                self.moss_prompt_audio_path = None

            def validate_security(self):
                assert isinstance(self.output_dir, Path)
                assert isinstance(self.credentials_dir, Path)
                assert isinstance(self.api_key_file, Path)
                assert isinstance(self.admin_credentials_file, Path)
                assert isinstance(self.runtime_config_file, Path)
                assert isinstance(self.model_dir, Path)
                events.append("validation")

        def fake_apply_env(cfg):
            events.append("environment")
            cfg.cache_max_items = 2

        def fake_load_runtime(cfg):
            events.append(("runtime", cfg.runtime_config_file))
            cfg.cache_max_items = 3

        monkeypatch.setattr(config_module, "TTSConfig", FakeConfig)
        monkeypatch.setattr(config_module, "apply_env", fake_apply_env)
        monkeypatch.setattr(config_module, "load_runtime_config", fake_load_runtime)

        cfg = config_module.load_config(
            cache_max_items=4,
            runtime_config_file=str(explicit_path),
        )

        assert cfg.cache_max_items == 4
        assert cfg.runtime_config_file == explicit_path
        assert events == [
            "defaults",
            "environment",
            ("runtime", initially_selected),
            "validation",
        ]

    def test_load_config_source_keeps_canonical_phase_order(self):
        """STATIC OWNERSHIP CONTRACT supplementing the facade contract."""

        function = _definition(_module_tree("config.py"), "load_config")
        lines = {
            name: min(
                node.lineno
                for node in ast.walk(function)
                if isinstance(node, ast.Call)
                and (
                    (isinstance(node.func, ast.Name) and node.func.id == name)
                    or (
                        isinstance(node.func, ast.Attribute)
                        and node.func.attr == name
                    )
                )
            )
            for name in ("TTSConfig", "apply_env", "load_runtime_config", "validate_security")
        }
        assert (
            lines["TTSConfig"]
            < lines["apply_env"]
            < lines["load_runtime_config"]
            < lines["validate_security"]
        )


class TestRuntimeConfigEnvelopeAndLegacyRead:
    def test_default_path_canonical_and_legacy_shapes_are_read_from_tmp_only(
        self, tmp_path
    ):
        """BEHAVIOR CONTRACT for path and reader format."""

        assert admin_schema.runtime_config_path(
            SimpleNamespace(runtime_config_file=None)
        ) == Path("/app/config/runtime-config.json")

        canonical = tmp_path / "canonical.json"
        legacy = tmp_path / "legacy.json"
        _write_runtime(canonical, {"cache_max_items": 21})
        _write_runtime(legacy, {"cache_max_items": 22}, envelope=False)

        assert admin_schema.read_runtime_config_values(canonical) == {
            "cache_max_items": 21
        }
        assert admin_schema.read_runtime_config_values(legacy) == {
            "cache_max_items": 22
        }

    def test_load_filters_unknown_cache_and_synthetic_secret_keys_then_rewrites(
        self, tmp_path
    ):
        """BEHAVIOR CONTRACT: filtering belongs to load_runtime_config."""

        cfg = _synthetic_config(tmp_path)
        cfg.model_source_effective = "huggingface"
        cfg.model_source_country = "US"
        cfg.model_source_hf_reachable = True
        cfg.model_source_modelscope_reachable = False
        path = admin_schema.runtime_config_path(cfg)
        raw_values = {
            "cache_max_items": "31",
            "removed_field": "ignored",
            "model_source_effective": "offline",
            "model_source_country": "CN",
            "model_source_hf_reachable": False,
            "model_source_modelscope_reachable": True,
            "HF_TOKEN": "synthetic-redacted-value",
        }
        _write_runtime(path, raw_values)

        # The low-level reader intentionally returns raw values; the loader owns
        # Admin allowlisting/coercion and canonical cleanup.
        assert admin_schema.read_runtime_config_values(path) == raw_values
        assert admin_schema.load_runtime_config(cfg) == ["cache_max_items"]

        assert cfg.cache_max_items == 31
        assert cfg.model_source_effective == "huggingface"
        assert cfg.model_source_country == "US"
        assert cfg.model_source_hf_reachable is True
        assert cfg.model_source_modelscope_reachable is False
        cleaned = json.loads(path.read_text(encoding="utf-8"))
        assert cleaned["version"] == 1
        assert isinstance(cleaned["updated_at"], int)
        assert cleaned["values"] == {"cache_max_items": 31}

    def test_successful_save_uses_versioned_envelope(self, tmp_path):
        """BEHAVIOR CONTRACT; exact timestamp is deliberately not frozen."""

        cfg = _synthetic_config(tmp_path)
        path = admin_schema.save_runtime_config_values(
            cfg, {"cache_max_items": "44"}
        )
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["version"] == 1
        assert isinstance(payload["updated_at"], int)
        assert payload["values"] == {"cache_max_items": 44}


class TestRuntimeConfigAtomicPersistence:
    def test_atomic_writer_orders_complete_temp_fsync_mode_and_replace(
        self, monkeypatch, tmp_path
    ):
        """BEHAVIOR CONTRACT for final-file atomic visibility."""

        path = tmp_path / "runtime-config.json"
        with path.open("w", encoding="utf-8") as handle:
            handle.write('{"old": true}\n')
        payload = {"version": 1, "updated_at": 123, "values": {"x": 1}}
        events: list[object] = []
        real_fsync = admin_schema.os.fsync
        real_chmod = admin_schema.os.chmod
        real_replace = admin_schema.os.replace

        def fake_fsync(fd):
            events.append(("fsync", fd))
            real_fsync(fd)

        def fake_chmod(temp, mode):
            events.append(("chmod", Path(temp), mode))
            real_chmod(temp, mode)

        def fake_replace(source, destination):
            source = Path(source)
            destination = Path(destination)
            assert destination.read_text(encoding="utf-8") == '{"old": true}\n'
            assert json.loads(source.read_text(encoding="utf-8")) == payload
            assert source.parent == destination.parent == tmp_path
            events.append(("replace", source, destination))
            real_replace(source, destination)

        monkeypatch.setattr(admin_schema.os, "fsync", fake_fsync)
        monkeypatch.setattr(admin_schema.os, "chmod", fake_chmod)
        monkeypatch.setattr(admin_schema.os, "replace", fake_replace)

        admin_schema._atomic_write_json(path, payload)

        assert [event[0] for event in events] == ["fsync", "chmod", "replace"]
        assert events[1][2] == 0o600
        assert events[2][2] == path
        assert json.loads(path.read_text(encoding="utf-8")) == payload
        assert not list(tmp_path.glob(f".{path.name}.*.tmp"))

    def test_atomic_writer_static_order_includes_flush_before_fsync(self):
        """STATIC OWNERSHIP CONTRACT for the operations hidden by file objects."""

        function = _definition(
            _module_tree("admin_config/schema.py"), "_atomic_write_json"
        )

        def first_line(name: str) -> int:
            return min(
                node.lineno
                for node in ast.walk(function)
                if isinstance(node, ast.Call)
                and (
                    (isinstance(node.func, ast.Name) and node.func.id == name)
                    or (
                        isinstance(node.func, ast.Attribute)
                        and node.func.attr == name
                    )
                )
            )

        assert (
            first_line("write")
            < first_line("flush")
            < first_line("fsync")
            < first_line("chmod")
            < first_line("replace")
        )


class TestRuntimeConfigLockOwnership:
    def test_fcntl_branch_wraps_read_merge_write_with_exclusive_lock(
        self, monkeypatch, tmp_path
    ):
        """BEHAVIOR/OWNERSHIP CONTRACT using fake fcntl."""

        cfg = _synthetic_config(tmp_path)
        path = admin_schema.runtime_config_path(cfg)
        events: list[object] = []

        fake_fcntl = SimpleNamespace(
            LOCK_EX="LOCK_EX",
            LOCK_UN="LOCK_UN",
            flock=lambda _fd, operation: events.append(("flock", operation)),
        )

        def fake_read(received):
            events.append(("read", received))
            return {"cache_max_bytes": 100}

        def fake_write(received, payload):
            events.append(("write", received, payload))

        monkeypatch.setattr(admin_schema, "fcntl", fake_fcntl)
        monkeypatch.setattr(admin_schema, "read_runtime_config_values", fake_read)
        monkeypatch.setattr(admin_schema, "_atomic_write_json", fake_write)

        assert (
            admin_schema.save_runtime_config_values(
                cfg, {"cache_max_items": 12}
            )
            == path
        )

        assert [event[0:2] for event in events] == [
            ("flock", "LOCK_EX"),
            ("read", path),
            ("write", path),
            ("flock", "LOCK_UN"),
        ]
        assert events[2][2]["values"] == {
            "cache_max_bytes": 100,
            "cache_max_items": 12,
        }

    def test_fcntl_unavailable_leaves_only_process_local_rlock(
        self, monkeypatch, tmp_path
    ):
        """CURRENT-BEHAVIOR CHARACTERIZATION, not a cross-process guarantee."""

        monkeypatch.setattr(admin_schema, "fcntl", None)
        path = tmp_path / "runtime-config.json"
        with admin_schema._runtime_config_file_lock(path):
            assert path.with_suffix(".json.lock").exists()

        tree = _module_tree("admin_config/schema.py")
        assignment = next(
            node
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name)
                and target.id == "_RUNTIME_CONFIG_LOCK"
                for target in node.targets
            )
        )
        assert isinstance(assignment.value, ast.Call)
        assert isinstance(assignment.value.func, ast.Attribute)
        assert assignment.value.func.attr == "RLock"
        assert hasattr(admin_schema._RUNTIME_CONFIG_LOCK, "acquire")
        assert hasattr(admin_schema._RUNTIME_CONFIG_LOCK, "release")
        assert type(admin_schema._RUNTIME_CONFIG_LOCK) is type(threading.RLock())

    def test_reader_and_info_do_not_acquire_writer_lock_or_apply_config(self):
        """STATIC OWNERSHIP CONTRACT."""

        tree = _module_tree("admin_config/schema.py")
        for owner in ("read_runtime_config_values", "runtime_config_info"):
            names = _call_names(_definition(tree, owner))
            assert "_runtime_config_file_lock" not in names
            assert "load_runtime_config" not in names


class TestRuntimeConfigMergeSemantics:
    def test_sequential_saves_merge_distinct_keys_and_last_same_key_wins(
        self, tmp_path
    ):
        """BEHAVIOR CONTRACT; sequential calls are not a process-race proof."""

        cfg = _synthetic_config(tmp_path)
        admin_schema.save_runtime_config_values(cfg, {"cache_max_items": 12})
        admin_schema.save_runtime_config_values(cfg, {"cache_max_bytes": 2048})
        admin_schema.save_runtime_config_values(cfg, {"cache_max_items": 13})

        payload = json.loads(
            admin_schema.runtime_config_path(cfg).read_text(encoding="utf-8")
        )
        assert payload["version"] == 1
        assert isinstance(payload["updated_at"], int)
        assert payload["values"] == {
            "cache_max_items": 13,
            "cache_max_bytes": 2048,
        }


class TestAdminMutationBeforePersistence:
    @pytest.mark.parametrize("owner", ["patch", "profile"])
    def test_persistence_failure_leaves_current_cfg_mutated_without_rollback(
        self, monkeypatch, tmp_path, owner
    ):
        """CURRENT-BEHAVIOR CHARACTERIZATION; NOT TRANSACTIONAL GUARANTEE."""

        cfg = _synthetic_config(tmp_path, value=10)
        other_worker = _synthetic_config(tmp_path / "other", value=10)
        path = admin_schema.runtime_config_path(cfg)
        _write_runtime(path, {"cache_max_items": 10})
        events: list[object] = []

        monkeypatch.setattr(
            admin_runtime,
            "apply_admin_config_values",
            lambda received, values: (
                setattr(received, "cache_max_items", values["cache_max_items"]),
                events.append(("apply", received.cache_max_items)),
                (["cache_max_items"], [], False),
            )[-1],
        )
        monkeypatch.setattr(
            admin_runtime,
            "_apply_quality_runtime_guards",
            lambda _cfg: [],
        )
        monkeypatch.setattr(
            admin_runtime,
            "profile_values",
            lambda _profile: {"cache_max_items": 27},
        )

        def failing_save(received, changed):
            events.append(("save", received.cache_max_items, dict(changed)))
            assert received.cache_max_items == 27
            raise OSError("synthetic persistence failure")

        monkeypatch.setattr(
            admin_runtime, "save_runtime_config_values", failing_save
        )

        with pytest.raises(OSError, match="synthetic persistence failure"):
            if owner == "patch":
                admin_runtime.apply_config_patch(
                    cfg, AdminConfigPatch(cache_max_items=27)
                )
            else:
                admin_runtime.apply_config_profile(cfg, "synthetic-profile")

        assert events == [
            ("apply", 27),
            ("save", 27, {"cache_max_items": 27}),
        ]
        assert cfg.cache_max_items == 27
        assert other_worker.cache_max_items == 10
        assert admin_schema.read_runtime_config_values(path) == {
            "cache_max_items": 10
        }


class TestExistingWorkerAndNewWorkerConvergence:
    def test_save_updates_current_worker_and_file_not_existing_other_worker(
        self, tmp_path
    ):
        """BEHAVIOR/CHARACTERIZATION: no background eventual convergence."""

        shared_path = tmp_path / "shared-runtime.json"
        worker_a = _synthetic_config(tmp_path / "a", value=10)
        worker_b = _synthetic_config(tmp_path / "b", value=10)
        worker_c = _synthetic_config(tmp_path / "c", value=10)
        for cfg in (worker_a, worker_b, worker_c):
            cfg.runtime_config_file = shared_path

        changed, restart, rebuild = admin_runtime.apply_config_patch(
            worker_a, AdminConfigPatch(cache_max_items=29)
        )
        assert (changed, restart, rebuild) == (["cache_max_items"], [], False)
        assert worker_a.cache_max_items == 29
        assert worker_b.cache_max_items == 10

        persisted_from_b = admin_schema.runtime_config_info(worker_b)
        assert persisted_from_b["values"]["cache_max_items"] == 29
        b_snapshot = admin_runtime.config_snapshot(worker_b)
        assert b_snapshot["cache_max_items"] == 10
        assert b_snapshot["runtime_config"]["values"]["cache_max_items"] == 29
        assert worker_b.cache_max_items == 10

        assert admin_schema.load_runtime_config(worker_c) == ["cache_max_items"]
        assert worker_c.cache_max_items == 29

    def test_admin_apply_and_info_owners_have_no_broadcast_poll_or_reload_calls(self):
        """STATIC OWNERSHIP CONTRACT bound to concrete request helpers."""

        runtime_tree = _module_tree("routes/admin_runtime.py")
        schema_tree = _module_tree("admin_config/schema.py")
        admin_tree = _module_tree("routes/admin.py")
        forbidden = {
            "broadcast",
            "publish",
            "subscribe",
            "send_signal",
            "load_config",
            "load_runtime_config",
            "create_app",
            "reload",
            "restart",
        }
        for node in (
            _definition(runtime_tree, "apply_config_patch"),
            _definition(runtime_tree, "apply_config_profile"),
            _definition(schema_tree, "runtime_config_info"),
            _definition(admin_tree, "admin_patch_config"),
            _definition(admin_tree, "admin_apply_profile"),
        ):
            assert not forbidden & _call_names(node)


class TestAdminSchemaApplyMetadata:
    def test_restart_and_legacy_rebuild_metadata_sets_are_exact(self):
        """STATIC/BEHAVIOR CONTRACT for the schema-owned field sets."""

        restart = {
            key
            for key, field in admin_schema.ADMIN_CONFIG_FIELDS.items()
            if field.restart
        }
        rebuild = {
            key
            for key, field in admin_schema.ADMIN_CONFIG_FIELDS.items()
            if field.rebuild_moss
        }
        assert restart == RESTART_FIELDS
        assert len(restart) == 10
        assert rebuild == REBUILD_FIELDS
        assert len(rebuild) == 8
        assert {
            "kokoro_process_isolation_enabled",
            "moss_process_isolation_enabled",
            "zipvoice_process_isolation_enabled",
        } <= rebuild

    def test_runtime_schema_excludes_provider_secret_values_and_env_copying(self):
        """STATIC OWNERSHIP CONTRACT; credential paths and values are distinct."""

        field_keys = set(admin_schema.ADMIN_CONFIG_FIELDS)
        field_envs = {
            field.env for field in admin_schema.ADMIN_CONFIG_FIELDS.values()
        }
        forbidden = {
            "HUGGINGFACE_TOKEN",
            "HF_TOKEN",
            "MODELSCOPE_API_TOKEN",
            "KOKORO_API_KEY",
            "KOKORO_AUTO_API_KEY",
            "admin_password",
        }
        assert not forbidden & field_keys
        assert not forbidden & field_envs

        schema_tree = _module_tree("admin_config/schema.py")
        for owner in ("save_runtime_config_values", "export_env_patch"):
            node = _definition(schema_tree, owner)
            assert "environ" not in _call_names(node)


class _FakeManager:
    def __init__(self, *, drop_result: bool = True):
        self.drop_result = drop_result
        self.events: list[object] = []

    def drop_model(self, model_id, *, force, raise_if_busy):
        self.events.append(("drop_model", model_id, force, raise_if_busy))
        return self.drop_result


class TestCurrentWorkerModelRebuild:
    @pytest.mark.parametrize(
        ("field", "target"),
        [
            ("kokoro_process_isolation_enabled", "kokoro"),
            ("moss_process_isolation_enabled", "moss"),
            ("zipvoice_process_isolation_enabled", "zipvoice"),
        ],
    )
    def test_rebuild_dispatch_targets_only_the_request_worker_manager(
        self, monkeypatch, tmp_path, field, target
    ):
        """BEHAVIOR CONTRACT via direct route endpoint invocation, not HTTP."""

        cfg = _synthetic_config(tmp_path)
        manager = _FakeManager()
        other_manager = _FakeManager()
        monkeypatch.setattr(
            admin_routes,
            "apply_config_patch",
            lambda _cfg, _req: ([field], [], True),
        )
        monkeypatch.setattr(
            admin_routes,
            "config_snapshot",
            lambda _cfg: {"worker": "current"},
        )
        monkeypatch.setattr(
            admin_routes,
            "admin_config_payload",
            lambda _cfg: {"values": {field: True}},
        )
        monkeypatch.setattr(
            admin_routes,
            "export_env_patch",
            lambda _values, *, only: f"only={','.join(only)}",
        )
        router = _build_admin_router(monkeypatch, cfg, manager)
        endpoint = _admin_endpoint(router, "/admin/api/config", "PATCH")

        result = asyncio.run(endpoint(AdminConfigPatch(**{field: True}), _=None))

        assert manager.events == [
            ("drop_model", target, False, False),
            ("cache_clear",),
        ]
        assert other_manager.events == []
        assert result == {
            "ok": True,
            "changed": [field],
            "restart_required": [],
            "model_rebuild_required": True,
            "rebuilt_models": [target],
            "config": {"worker": "current"},
            "env_patch": f"only={field}",
        }

    def test_busy_or_not_loaded_target_remains_required_but_not_rebuilt(
        self, monkeypatch, tmp_path
    ):
        """BEHAVIOR CONTRACT for current false drop_model response."""

        field = "moss_process_isolation_enabled"
        cfg = _synthetic_config(tmp_path)
        manager = _FakeManager(drop_result=False)
        monkeypatch.setattr(
            admin_routes,
            "apply_config_patch",
            lambda _cfg, _req: ([field], [], True),
        )
        monkeypatch.setattr(admin_routes, "config_snapshot", lambda _cfg: {})
        monkeypatch.setattr(
            admin_routes,
            "admin_config_payload",
            lambda _cfg: {"values": {field: True}},
        )
        monkeypatch.setattr(
            admin_routes, "export_env_patch", lambda _values, *, only: ""
        )
        router = _build_admin_router(monkeypatch, cfg, manager)
        endpoint = _admin_endpoint(router, "/admin/api/config", "PATCH")

        result = asyncio.run(endpoint(AdminConfigPatch(**{field: True}), _=None))

        assert result["model_rebuild_required"] is True
        assert result["rebuilt_models"] == []
        assert manager.events == [("drop_model", "moss", False, False)]


class TestRestartAdvisoryBoundary:
    def test_restart_required_is_response_advice_not_restart_action(
        self, monkeypatch, tmp_path
    ):
        """BEHAVIOR/OWNERSHIP CONTRACT via direct endpoint invocation."""

        cfg = _synthetic_config(tmp_path)
        manager = _FakeManager()
        field = "rate_limit_qps"
        monkeypatch.setattr(
            admin_routes,
            "apply_config_patch",
            lambda _cfg, _req: ([field], [field], False),
        )
        monkeypatch.setattr(admin_routes, "config_snapshot", lambda _cfg: {})
        monkeypatch.setattr(
            admin_routes,
            "admin_config_payload",
            lambda _cfg: {"values": {field: 4.0}},
        )
        monkeypatch.setattr(
            admin_routes, "export_env_patch", lambda _values, *, only: ""
        )
        router = _build_admin_router(monkeypatch, cfg, manager)
        endpoint = _admin_endpoint(router, "/admin/api/config", "PATCH")

        result = asyncio.run(endpoint(AdminConfigPatch(rate_limit_qps=4.0), _=None))

        assert result["restart_required"] == [field]
        assert result["model_rebuild_required"] is False
        assert result["rebuilt_models"] == []
        assert manager.events == []

        route_node = _definition(_module_tree("routes/admin.py"), "admin_patch_config")
        assert not {
            "_exit",
            "exit",
            "terminate",
            "kill",
            "create_app",
            "load_config",
            "restart",
            "reload",
        } & _call_names(route_node)


class TestRuntimeConfigObservability:
    def test_info_reads_file_each_time_without_mutating_current_config(
        self, tmp_path
    ):
        """BEHAVIOR/OWNERSHIP CONTRACT."""

        cfg = _synthetic_config(tmp_path, value=10)
        path = admin_schema.runtime_config_path(cfg)
        before = dict(vars(cfg))
        _write_runtime(path, {"cache_max_items": 20})

        first = admin_schema.runtime_config_info(cfg)
        _write_runtime(path, {"cache_max_items": 21, "cache_max_bytes": 4096})
        second = admin_schema.runtime_config_info(cfg)

        assert first == {
            "path": str(path),
            "exists": True,
            "field_count": 1,
            "values": {"cache_max_items": 20},
        }
        assert second == {
            "path": str(path),
            "exists": True,
            "field_count": 2,
            "values": {"cache_max_items": 21, "cache_max_bytes": 4096},
        }
        assert vars(cfg) == before
        assert not MISSING_CONVERGENCE_FIELDS & set(second)

    def test_config_snapshot_is_current_worker_scope_and_country_is_unexposed(
        self, tmp_path
    ):
        """BEHAVIOR/OWNERSHIP CONTRACT with current response keys."""

        shared = tmp_path / "shared.json"
        worker_a = _synthetic_config(tmp_path / "a")
        worker_b = _synthetic_config(tmp_path / "b")
        for cfg in (worker_a, worker_b):
            cfg.runtime_config_file = shared
        _write_runtime(shared, {"cache_max_items": 77})

        worker_a.model_source = "huggingface"
        worker_a.model_source_effective = "huggingface"
        worker_a.model_source_country = "US"
        worker_a.model_source_hf_reachable = True
        worker_a.model_source_modelscope_reachable = False
        worker_b.model_source = "modelscope"
        worker_b.model_source_effective = "modelscope"
        worker_b.model_source_country = "CN"
        worker_b.model_source_hf_reachable = False
        worker_b.model_source_modelscope_reachable = True

        snapshot_a = admin_runtime.config_snapshot(worker_a)
        snapshot_b = admin_runtime.config_snapshot(worker_b)

        assert snapshot_a["model_source"] == "huggingface"
        assert snapshot_a["model_source_effective"] == "huggingface"
        assert snapshot_a["model_source_hf_reachable"] is True
        assert snapshot_a["model_source_modelscope_reachable"] is False
        assert snapshot_b["model_source"] == "modelscope"
        assert snapshot_b["model_source_effective"] == "modelscope"
        assert snapshot_b["model_source_hf_reachable"] is False
        assert snapshot_b["model_source_modelscope_reachable"] is True
        assert "model_source_country" not in snapshot_a
        assert "model_source_country" not in snapshot_b
        assert snapshot_a["runtime_config"]["values"]["cache_max_items"] == 77
        assert snapshot_b["runtime_config"]["values"]["cache_max_items"] == 77
        assert not MISSING_CONVERGENCE_FIELDS & set(snapshot_a)
        assert not MISSING_CONVERGENCE_FIELDS & set(snapshot_b)


class TestAdminUserVisibleFeedbackBoundary:
    def test_save_feedback_priority_and_moss_specific_wording_are_characterized(self):
        """CURRENT-BEHAVIOR CHARACTERIZATION; no UI copy change."""

        source = (PACKAGE_ROOT / "static" / "admin.js").read_text(encoding="utf-8")
        start = source.index("async function saveConfig()")
        end = source.index("async function applyProfile(", start)
        save = source[start:end]
        assert (
            save.index("if (!changed)")
            < save.index("else if ((result.rebuilt_models || []).length)")
            < save.index("else if (result.model_rebuild_required)")
            < save.index("else if ((result.restart_required || []).length)")
            < save.index("toast(t('toast.config_saved', { count: changed }))")
        )

        zh = (
            PACKAGE_ROOT / "static" / "locale" / "admin" / "messages.zh-cn.js"
        ).read_text(encoding="utf-8")
        en = (
            PACKAGE_ROOT / "static" / "locale" / "admin" / "messages.en.js"
        ).read_text(encoding="utf-8")
        assert "'toast.config_saved_rebuilt': '已保存 {count} 项配置，MOSS 已重建'" in zh
        assert (
            "'toast.config_saved_rebuilt': "
            "'Saved {count} configuration change(s); MOSS rebuilt'"
        ) in en
        assert "restart the service for them to take effect" in en
