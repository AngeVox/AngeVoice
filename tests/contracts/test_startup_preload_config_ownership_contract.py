"""Startup Preload declaration/default ownership contracts.

Current-state tests freeze the two-field flat facade and preserve the existing
ENV, Admin/runtime, worker, and lifespan owners. The two future-state tests are
intentionally RED until a defaults-only metadata owner exists and ``TTSConfig``
genuinely consumes it.

Model loading, asset acquisition, process isolation, and preload failure policy
remain covered by their existing lifecycle contracts and are not moved here.
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
from kokoro_tts import config_env, server
from kokoro_tts.admin_config import (
    ADMIN_CONFIG_FIELDS,
    apply_admin_config_values,
)
from kokoro_tts.config import TTSConfig


pytestmark = pytest.mark.contract

PACKAGE_ROOT = Path(config_module.__file__).parent
STARTUP_PRELOAD_FIELDS = (
    "startup_preload_enabled",
    "startup_preload_model",
)
ADJACENT_EXCLUSIONS = {
    "enabled_models",
    "default_model",
    "model_switch_enabled",
    "model_unload_on_switch",
    "model_switch_timeout_seconds",
}
EXPECTED_FACADE = (
    ("startup_preload_enabled", bool, False),
    ("startup_preload_model", str, "kokoro"),
)
EXPECTED_ENV = {
    "ANGEVOICE_STARTUP_PRELOAD_ENABLED": "startup_preload_enabled",
    "ANGEVOICE_STARTUP_PRELOAD_MODEL": "startup_preload_model",
}
EXPECTED_WORKER_EXPORTS = dict(EXPECTED_ENV)
FUTURE_OWNER_MODULE = "kokoro_tts.startup_preload_config_metadata"


def _module_tree(module) -> ast.Module:  # noqa: ANN001
    return ast.parse(Path(module.__file__).read_text(encoding="utf-8"))


def _definition(tree: ast.AST, name: str) -> ast.AST:
    return next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and node.name == name
    )


def _call_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for item in ast.walk(node):
        if not isinstance(item, ast.Call):
            continue
        if isinstance(item.func, ast.Name):
            names.add(item.func.id)
        elif isinstance(item.func, ast.Attribute):
            names.add(item.func.attr)
    return names


def _ttsconfig_assignments(tree: ast.Module) -> dict[str, ast.AnnAssign]:
    config_class = _definition(tree, "TTSConfig")
    assert isinstance(config_class, ast.ClassDef)
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
        ).endswith("startup_preload_config_metadata"):
            bindings.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is None:
            bindings.update(
                alias.asname or alias.name
                for alias in node.names
                if alias.name == "startup_preload_config_metadata"
            )
        elif isinstance(node, ast.Import):
            bindings.update(
                alias.asname or alias.name.split(".")[-1]
                for alias in node.names
                if alias.name.endswith(".startup_preload_config_metadata")
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


def test_current_startup_preload_flat_facade_is_exact_and_compatible(tmp_path) -> None:
    fields = dataclasses.fields(TTSConfig)
    field_names = tuple(field.name for field in fields)
    hints = get_type_hints(TTSConfig)
    selected = tuple(
        (name, hints[name], next(field for field in fields if field.name == name).default)
        for name in STARTUP_PRELOAD_FIELDS
    )

    assert len(fields) == 179
    assert sum(field.init for field in fields) == 177
    assert selected == EXPECTED_FACADE
    assert tuple(name for name in field_names if name.startswith("startup_preload_")) == (
        STARTUP_PRELOAD_FIELDS
    )
    first = field_names.index(STARTUP_PRELOAD_FIELDS[0])
    assert field_names[first - 1 : first + 3] == (
        "default_model",
        *STARTUP_PRELOAD_FIELDS,
        "model_switch_enabled",
    )
    assert ADJACENT_EXCLUSIONS.isdisjoint(STARTUP_PRELOAD_FIELDS)

    config = TTSConfig(
        model_dir=tmp_path / "models",
        startup_preload_enabled=True,
        startup_preload_model="moss",
    )
    assert tuple(getattr(config, name) for name in STARTUP_PRELOAD_FIELDS) == (
        True,
        "moss",
    )
    assert not hasattr(config, "startup_preload")


def test_current_startup_preload_env_subset_and_application_are_preserved(
    monkeypatch, tmp_path
) -> None:
    assert {
        env: attr
        for env, attr in config_env.BOOL_ENV.items()
        if attr in STARTUP_PRELOAD_FIELDS
    } == {"ANGEVOICE_STARTUP_PRELOAD_ENABLED": "startup_preload_enabled"}
    assert {
        env: attr
        for env, attr in config_env.STR_ENV.items()
        if attr in STARTUP_PRELOAD_FIELDS
    } == {"ANGEVOICE_STARTUP_PRELOAD_MODEL": "startup_preload_model"}
    assert not {
        spec.attr
        for mapping in (config_env.INT_ENV, config_env.FLOAT_ENV)
        for spec in mapping.values()
    } & set(STARTUP_PRELOAD_FIELDS)

    monkeypatch.setenv("ANGEVOICE_STARTUP_PRELOAD_ENABLED", "true")
    monkeypatch.setenv("ANGEVOICE_STARTUP_PRELOAD_MODEL", "moss")
    config = TTSConfig(model_dir=tmp_path / "models")
    config_env.apply_env(config)
    assert (config.startup_preload_enabled, config.startup_preload_model) == (
        True,
        "moss",
    )


def test_current_startup_preload_admin_runtime_rows_are_preserved(tmp_path) -> None:
    enabled = ADMIN_CONFIG_FIELDS["startup_preload_enabled"]
    model = ADMIN_CONFIG_FIELDS["startup_preload_model"]

    assert (enabled.group, enabled.type, enabled.default, enabled.restart) == (
        "service",
        "bool",
        False,
        True,
    )
    assert (model.group, model.type, model.default, model.restart) == (
        "service",
        "choice",
        "kokoro",
        True,
    )
    assert tuple(choice[0] for choice in model.choices) == (
        "kokoro",
        "moss",
        "zipvoice",
    )

    config = TTSConfig(model_dir=tmp_path / "models")
    changed, restart_required, rebuild_moss = apply_admin_config_values(
        config,
        {
            "startup_preload_enabled": True,
            "startup_preload_model": "moss",
        },
    )
    assert changed == list(STARTUP_PRELOAD_FIELDS)
    assert restart_required == list(STARTUP_PRELOAD_FIELDS)
    assert rebuild_moss is False
    assert (config.startup_preload_enabled, config.startup_preload_model) == (
        True,
        "moss",
    )
    assert "warm_model" not in _call_names(
        _definition(
            _module_tree(importlib.import_module("kokoro_tts.admin_config.schema")),
            "apply_admin_config_values",
        )
    )


def test_current_startup_preload_worker_projection_is_exact() -> None:
    actual = {
        env: attr
        for env, attr in server._WORKER_ENV_EXPORTS.items()
        if attr in STARTUP_PRELOAD_FIELDS
    }
    assert actual == EXPECTED_WORKER_EXPORTS
    assert actual == EXPECTED_ENV


def test_current_startup_preload_lifespan_keeps_flat_startup_only_consumption() -> None:
    tree = _module_tree(server)
    lifespan = _definition(_definition(tree, "create_app"), "lifespan")
    source = ast.unparse(lifespan)
    calls = _call_names(lifespan)

    assert all(name in source for name in STARTUP_PRELOAD_FIELDS)
    assert "cfg.startup_preload." not in source
    assert {"switch_model", "list_specs", "warm_model"} <= calls
    assert not {"create_task", "run_in_executor", "to_thread"} & calls

    switch = next(
        node
        for node in ast.walk(lifespan)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "switch_model"
    )
    warm = next(
        node
        for node in ast.walk(lifespan)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "warm_model"
    )
    yield_node = next(node for node in ast.walk(lifespan) if isinstance(node, ast.Yield))
    assert switch.lineno < warm.lineno < yield_node.lineno

    availability_branch = next(
        node
        for node in ast.walk(lifespan)
        if isinstance(node, ast.If)
        and "preload_model in available_models" in ast.unparse(node.test)
    )
    assert "warm_model" in _call_names(ast.Module(body=availability_branch.body))
    assert "warm_model" not in _call_names(ast.Module(body=availability_branch.orelse))


def test_current_startup_preload_precedence_and_restart_boundary(
    monkeypatch, tmp_path
) -> None:
    events: list[str] = []

    def apply_env(config: TTSConfig) -> None:
        events.append("env")
        config.startup_preload_enabled = True
        config.startup_preload_model = "moss"

    def load_runtime(config: TTSConfig) -> None:
        events.append("runtime")
        config.startup_preload_enabled = False
        config.startup_preload_model = "zipvoice"

    monkeypatch.setattr(config_module, "apply_env", apply_env)
    monkeypatch.setattr(config_module, "load_runtime_config", load_runtime)
    config = config_module.load_config(
        model_dir=str(tmp_path / "models"),
        startup_preload_enabled=True,
        startup_preload_model="kokoro",
    )

    assert events == ["env", "runtime"]
    assert (config.startup_preload_enabled, config.startup_preload_model) == (
        True,
        "kokoro",
    )
    assert all(ADMIN_CONFIG_FIELDS[name].restart for name in STARTUP_PRELOAD_FIELDS)


def test_current_startup_preload_owner_excludes_env_admin_server_and_models() -> None:
    assert STARTUP_PRELOAD_FIELDS == (
        "startup_preload_enabled",
        "startup_preload_model",
    )
    assert ADJACENT_EXCLUSIONS == {
        "enabled_models",
        "default_model",
        "model_switch_enabled",
        "model_unload_on_switch",
        "model_switch_timeout_seconds",
    }
    assert not any(
        isinstance(node, (ast.Import, ast.ImportFrom))
        and "startup_preload_config_metadata" in ast.unparse(node)
        for node in _module_tree(server).body
    )


def test_future_startup_preload_declaration_owner_is_immutable_defaults_only() -> None:
    spec = importlib.util.find_spec(FUTURE_OWNER_MODULE)
    assert spec is not None, (
        "missing declaration-only Startup Preload owner: expected "
        f"{FUTURE_OWNER_MODULE}.STARTUP_PRELOAD_CONFIG_METADATA"
    )
    module = importlib.import_module(FUTURE_OWNER_MODULE)
    metadata = module.STARTUP_PRELOAD_CONFIG_METADATA
    by_key = module.STARTUP_PRELOAD_CONFIG_BY_KEY

    assert isinstance(metadata, tuple)
    assert tuple((item.key, item.annotation, item.default) for item in metadata) == (
        EXPECTED_FACADE
    )
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
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError, TypeError)):
            item.default = object()

    assert isinstance(by_key, MappingProxyType)
    assert tuple(by_key) == STARTUP_PRELOAD_FIELDS
    assert all(by_key[item.key] is item for item in metadata)
    with pytest.raises(TypeError):
        by_key["startup_preload_enabled"] = metadata[0]

    owner_tree = ast.parse(Path(spec.origin).read_text(encoding="utf-8"))
    imported_modules = {
        node.module or ""
        for node in owner_tree.body
        if isinstance(node, ast.ImportFrom)
    } | {
        alias.name
        for node in owner_tree.body
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert not any(
        token in imported.lower()
        for imported in imported_modules
        for token in ("config_env", "admin_config", "server", "engine", "asset")
    )


def test_future_startup_preload_ttsconfig_defaults_depend_on_owner() -> None:
    tree = _module_tree(config_module)
    owner_bindings = _owner_import_bindings(tree)
    assert owner_bindings, (
        "TTSConfig must import the Startup Preload declaration owner; adding a "
        "dead STARTUP_PRELOAD_CONFIG_METADATA tuple is insufficient"
    )
    definitions = _top_level_definitions(tree)
    assignments = _ttsconfig_assignments(tree)

    for field_name in STARTUP_PRELOAD_FIELDS:
        value = assignments[field_name].value
        assert value is not None
        assert _depends_on_owner(
            value,
            owner_bindings=owner_bindings,
            definitions=definitions,
        ), (
            f"TTSConfig.{field_name} must derive its default from the "
            "Startup Preload owner"
        )
