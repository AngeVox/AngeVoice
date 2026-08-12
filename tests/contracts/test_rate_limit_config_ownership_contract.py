"""Rate Limit configuration ownership contracts.

Current-state tests freeze the two-field flat facade and the existing ENV,
Admin/runtime, worker, profile, and middleware boundaries.  The two future
tests intentionally stay red until a declaration-only defaults owner exists
and ``TTSConfig`` consumes it.
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
import importlib.util
from pathlib import Path
from types import MappingProxyType
from typing import get_type_hints

import pytest

from kokoro_tts import config as config_module
from kokoro_tts import config_env
from kokoro_tts.admin_config import (
    ADMIN_CONFIG_FIELDS,
    ADMIN_CONFIG_PROFILES,
    apply_admin_config_values,
    validate_admin_config_values,
)
from kokoro_tts.config import TTSConfig
from kokoro_tts.rate_limit import TokenBucket


pytestmark = pytest.mark.contract


RATE_LIMIT_FIELDS = (
    "rate_limit_qps",
    "rate_limit_burst",
)

EXCLUDED_ADJACENT_FIELDS = (
    "max_queue_length",
    "trust_proxy_headers",
)

EXPECTED_FACADE = (
    ("rate_limit_qps", float, 10.0),
    ("rate_limit_burst", int, 20),
)

EXPECTED_ADMIN = (
    (
        "rate_limit_qps",
        "KOKORO_RATE_LIMIT_QPS",
        "security",
        "float",
        10.0,
        0,
        1000,
        0.1,
        True,
    ),
    (
        "rate_limit_burst",
        "KOKORO_RATE_LIMIT_BURST",
        "security",
        "int",
        20,
        0,
        10000,
        1,
        True,
    ),
)

EXPECTED_WORKER_EXPORTS = {
    "KOKORO_RATE_LIMIT_QPS": "rate_limit_qps",
    "KOKORO_RATE_LIMIT_BURST": "rate_limit_burst",
}

EXPECTED_PROFILE_VALUES = {
    "deploy_lan_default": (10.0, 20),
    "deploy_public_hardened": (3.0, 6),
}

FUTURE_OWNER_MODULE = "kokoro_tts.rate_limit_config_metadata"


def _module_tree(module) -> ast.Module:  # noqa: ANN001
    return ast.parse(Path(module.__file__).read_text(encoding="utf-8"))


def _ttsconfig_assignments(tree: ast.Module) -> dict[str, ast.AnnAssign]:
    config_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "TTSConfig"
    )
    return {
        node.target.id: node
        for node in config_class.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }


def _owner_import_bindings(tree: ast.Module) -> set[str]:
    bindings: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and (
            node.module or ""
        ).endswith("rate_limit_config_metadata"):
            bindings.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            bindings.update(
                alias.asname or alias.name.split(".")[-1]
                for alias in node.names
                if alias.name.endswith(".rate_limit_config_metadata")
            )
    return bindings


def _top_level_definitions(tree: ast.Module) -> dict[str, ast.AST]:
    definitions: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            definitions[node.name] = node
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    definitions[target.id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.value is not None:
                definitions[node.target.id] = node.value
    return definitions


def _depends_on_owner(
    node: ast.AST,
    *,
    owner_bindings: set[str],
    definitions: dict[str, ast.AST],
    resolving: frozenset[str] = frozenset(),
) -> bool:
    if isinstance(node, ast.Name):
        if node.id in owner_bindings:
            return True
        if node.id in definitions and node.id not in resolving:
            return _depends_on_owner(
                definitions[node.id],
                owner_bindings=owner_bindings,
                definitions=definitions,
                resolving=resolving | {node.id},
            )
    return any(
        _depends_on_owner(
            child,
            owner_bindings=owner_bindings,
            definitions=definitions,
            resolving=resolving,
        )
        for child in ast.iter_child_nodes(node)
    )


def _admin_row(field) -> tuple[object, ...]:  # noqa: ANN001
    return (
        field.key,
        field.env,
        field.group,
        field.type,
        field.default,
        field.min_value,
        field.max_value,
        field.step,
        field.restart,
    )


def test_current_rate_limit_flat_facade_is_exact_and_compatible() -> None:
    fields = dataclasses.fields(TTSConfig)
    names = tuple(field.name for field in fields)
    by_name = {field.name: field for field in fields}
    annotations = get_type_hints(TTSConfig)

    assert (len(fields), sum(field.init for field in fields)) == (179, 177)
    assert tuple(field.name for field in fields if not field.init) == (
        "_voices_cache",
        "_voices_cache_signature",
    )
    start = names.index(RATE_LIMIT_FIELDS[0])
    assert names[start : start + len(RATE_LIMIT_FIELDS)] == RATE_LIMIT_FIELDS
    assert not set(EXCLUDED_ADJACENT_FIELDS).intersection(RATE_LIMIT_FIELDS)

    for key, annotation, default in EXPECTED_FACADE:
        assert annotations[key] is annotation
        assert by_name[key].default == default
        assert by_name[key].init is True

    configured = TTSConfig(rate_limit_qps=2.5, rate_limit_burst=7)
    assert tuple(getattr(configured, key) for key in RATE_LIMIT_FIELDS) == (
        2.5,
        7,
    )
    assert not hasattr(configured, "rate_limit")


def test_current_rate_limit_env_subset_and_behavior_are_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    qps_spec = config_env.FLOAT_ENV["KOKORO_RATE_LIMIT_QPS"]
    burst_spec = config_env.INT_ENV["KOKORO_RATE_LIMIT_BURST"]
    assert (qps_spec.attr, qps_spec.min_value, qps_spec.max_value) == (
        "rate_limit_qps",
        0.0,
        None,
    )
    assert (burst_spec.attr, burst_spec.min_value, burst_spec.max_value) == (
        "rate_limit_burst",
        0,
        None,
    )

    projected: dict[str, list[str]] = {key: [] for key in RATE_LIMIT_FIELDS}
    for env_name, spec in config_env.FLOAT_ENV.items():
        if spec.attr in projected:
            projected[spec.attr].append(env_name)
    for env_name, spec in config_env.INT_ENV.items():
        if spec.attr in projected:
            projected[spec.attr].append(env_name)
    for env_name, attr in config_env.STR_ENV.items():
        if attr in projected:
            projected[attr].append(env_name)
    for env_name, attr in config_env.BOOL_ENV.items():
        if attr in projected:
            projected[attr].append(env_name)
    assert projected == {
        "rate_limit_qps": ["KOKORO_RATE_LIMIT_QPS"],
        "rate_limit_burst": ["KOKORO_RATE_LIMIT_BURST"],
    }

    config = TTSConfig(rate_limit_qps=4.5, rate_limit_burst=9)
    monkeypatch.setattr(
        config_env.os,
        "environ",
        {
            "KOKORO_RATE_LIMIT_QPS": "not-a-float",
            "KOKORO_RATE_LIMIT_BURST": "not-an-int",
        },
    )
    config_env.apply_env(config)
    assert (config.rate_limit_qps, config.rate_limit_burst) == (4.5, 9)

    monkeypatch.setattr(
        config_env.os,
        "environ",
        {
            "KOKORO_RATE_LIMIT_QPS": "-7",
            "KOKORO_RATE_LIMIT_BURST": "-7",
        },
    )
    config_env.apply_env(config)
    assert (config.rate_limit_qps, config.rate_limit_burst) == (0.0, 0)


def test_current_rate_limit_admin_runtime_rows_and_restart_advice_are_exact() -> None:
    admin_keys = tuple(
        key for key in ADMIN_CONFIG_FIELDS if key in RATE_LIMIT_FIELDS
    )
    assert admin_keys == RATE_LIMIT_FIELDS
    assert tuple(_admin_row(ADMIN_CONFIG_FIELDS[key]) for key in admin_keys) == (
        EXPECTED_ADMIN
    )

    cleaned = validate_admin_config_values(
        {"rate_limit_qps": "2.5", "rate_limit_burst": "7"}
    )
    assert cleaned == {"rate_limit_qps": 2.5, "rate_limit_burst": 7}

    config = TTSConfig()
    changed, restart_required, rebuild_moss = apply_admin_config_values(
        config, cleaned
    )
    assert changed == list(RATE_LIMIT_FIELDS)
    assert restart_required == list(RATE_LIMIT_FIELDS)
    assert rebuild_moss is False
    assert (config.rate_limit_qps, config.rate_limit_burst) == (2.5, 7)


def test_current_rate_limit_profiles_remain_independent_policy_presets() -> None:
    actual = {
        profile: tuple(
            ADMIN_CONFIG_PROFILES[profile]["values"][key]
            for key in RATE_LIMIT_FIELDS
        )
        for profile in EXPECTED_PROFILE_VALUES
    }
    assert actual == EXPECTED_PROFILE_VALUES
    assert actual["deploy_lan_default"] == tuple(
        default for _key, _annotation, default in EXPECTED_FACADE
    )
    assert actual["deploy_public_hardened"] != actual["deploy_lan_default"]


def test_current_rate_limit_worker_projection_is_exact() -> None:
    from kokoro_tts.server import _WORKER_ENV_EXPORTS

    assert {
        env_name: attr
        for env_name, attr in _WORKER_ENV_EXPORTS.items()
        if attr in RATE_LIMIT_FIELDS
    } == EXPECTED_WORKER_EXPORTS


def test_current_rate_limit_consumer_and_runtime_policy_boundaries_are_preserved(
) -> None:
    from kokoro_tts import rate_limit, server

    server_tree = _module_tree(server)
    create_app = next(
        node
        for node in server_tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "create_app"
    )
    flat_reads = {
        node.attr
        for node in ast.walk(create_app)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "cfg"
    }
    assert set(RATE_LIMIT_FIELDS).issubset(flat_reads)
    assert set(EXCLUDED_ADJACENT_FIELDS).issubset(flat_reads)
    assert not _owner_import_bindings(server_tree)
    assert not _owner_import_bindings(_module_tree(rate_limit))

    bucket = TokenBucket(qps=-1.0, burst=0)
    assert bucket.acquire() is True
    assert bucket.acquire() is False
    assert bucket.retry_after == 1.0


def test_current_rate_limit_load_config_precedence_is_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    def apply_env(config: TTSConfig) -> None:
        events.append("env")
        config.rate_limit_qps = 2.0
        config.rate_limit_burst = 4

    def load_runtime_config(config: TTSConfig) -> None:
        events.append("runtime")
        config.rate_limit_qps = 3.0
        config.rate_limit_burst = 6

    monkeypatch.setattr(config_module, "apply_env", apply_env)
    monkeypatch.setattr(config_module, "load_runtime_config", load_runtime_config)

    runtime = config_module.load_config()
    assert events == ["env", "runtime"]
    assert (runtime.rate_limit_qps, runtime.rate_limit_burst) == (3.0, 6)

    events.clear()
    explicit = config_module.load_config(
        rate_limit_qps=5.0,
        rate_limit_burst=10,
    )
    assert events == ["env", "runtime"]
    assert (explicit.rate_limit_qps, explicit.rate_limit_burst) == (5.0, 10)


def test_future_rate_limit_declaration_owner_is_immutable_defaults_only() -> None:
    spec = importlib.util.find_spec(FUTURE_OWNER_MODULE)
    assert spec is not None, (
        "missing declaration-only Rate Limit owner: expected "
        f"{FUTURE_OWNER_MODULE}.RATE_LIMIT_CONFIG_METADATA"
    )
    module = importlib.import_module(FUTURE_OWNER_MODULE)
    metadata = module.RATE_LIMIT_CONFIG_METADATA
    by_key = module.RATE_LIMIT_CONFIG_BY_KEY

    assert isinstance(metadata, tuple)
    assert len(metadata) == 2
    assert tuple(
        (item.key, item.annotation, item.default) for item in metadata
    ) == EXPECTED_FACADE
    assert [
        name for name, value in vars(module).items() if value is metadata
    ] == ["RATE_LIMIT_CONFIG_METADATA"]

    declaration_type = type(metadata[0])
    assert dataclasses.is_dataclass(declaration_type)
    assert declaration_type.__dataclass_params__.frozen is True
    assert tuple(field.name for field in dataclasses.fields(declaration_type)) == (
        "key",
        "annotation",
        "default",
    )
    assert tuple(getattr(declaration_type, "__slots__", ())) == (
        "key",
        "annotation",
        "default",
    )
    for item in metadata:
        with pytest.raises(dataclasses.FrozenInstanceError):
            item.default = object()

    assert isinstance(by_key, MappingProxyType)
    assert tuple(by_key) == RATE_LIMIT_FIELDS
    assert all(by_key[item.key] is item for item in metadata)
    with pytest.raises(TypeError):
        by_key["rate_limit_qps"] = metadata[0]


def test_future_rate_limit_ttsconfig_defaults_depend_on_owner() -> None:
    tree = _module_tree(config_module)
    owner_bindings = _owner_import_bindings(tree)
    assert owner_bindings, (
        "TTSConfig must import the Rate Limit declaration owner; adding a dead "
        "RATE_LIMIT_CONFIG_METADATA tuple is insufficient"
    )
    definitions = _top_level_definitions(tree)
    assignments = _ttsconfig_assignments(tree)

    for field_name in RATE_LIMIT_FIELDS:
        value = assignments[field_name].value
        assert value is not None
        assert _depends_on_owner(
            value,
            owner_bindings=owner_bindings,
            definitions=definitions,
        ), (
            f"TTSConfig.{field_name} must derive its default from the "
            "Rate Limit owner"
        )
