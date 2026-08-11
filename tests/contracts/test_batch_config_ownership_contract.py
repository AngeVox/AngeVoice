"""Batch configuration ownership contracts.

Current-state tests freeze the public flat facade and existing ENV/runtime
owners.  Future-state tests intentionally stay red until a real declaration
owner exists and ``TTSConfig`` consumes it.
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
import importlib.util
from pathlib import Path
from typing import get_type_hints

import pytest

from kokoro_tts import config as config_module
from kokoro_tts import config_env, config_env_domain
from kokoro_tts.admin_config import ADMIN_CONFIG_FIELDS, load_runtime_config
from kokoro_tts.config import TTSConfig


BATCH_FIELDS = (
    "batch_enabled",
    "batch_max_items",
    "batch_concurrency",
)

EXPECTED_BATCH = (
    ("batch_enabled", bool, True, "KOKORO_BATCH_ENABLED", None),
    (
        "batch_max_items",
        int,
        20,
        "KOKORO_BATCH_MAX_ITEMS",
        "batch_max_items",
    ),
    (
        "batch_concurrency",
        int,
        1,
        "KOKORO_BATCH_CONCURRENCY",
        "batch_concurrency",
    ),
)

EXPECTED_INT_ENV = (
    ("KOKORO_BATCH_MAX_ITEMS", "batch_max_items", 1, None),
    ("KOKORO_BATCH_CONCURRENCY", "batch_concurrency", 1, None),
)

EXPECTED_WORKER_EXPORTS = {
    "KOKORO_BATCH_ENABLED": "batch_enabled",
    "KOKORO_BATCH_MAX_ITEMS": "batch_max_items",
    "KOKORO_BATCH_CONCURRENCY": "batch_concurrency",
}


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


def _batch_owner_import_bindings(tree: ast.Module) -> set[str]:
    bindings: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "batch_config_metadata":
            bindings.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is None:
            bindings.update(
                alias.asname or alias.name
                for alias in node.names
                if alias.name == "batch_config_metadata"
            )
        elif isinstance(node, ast.Import):
            bindings.update(
                alias.asname or alias.name.split(".")[-1]
                for alias in node.names
                if alias.name.endswith(".batch_config_metadata")
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


def _depends_on_batch_owner(
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
            return _depends_on_batch_owner(
                definitions[node.id],
                owner_bindings=owner_bindings,
                definitions=definitions,
                resolving=resolving | {node.id},
            )
    return any(
        _depends_on_batch_owner(
            child,
            owner_bindings=owner_bindings,
            definitions=definitions,
            resolving=resolving,
        )
        for child in ast.iter_child_nodes(node)
    )


def _flat_batch_references(tree: ast.Module) -> set[str]:
    references: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "cfg"
            and node.attr in BATCH_FIELDS
        ):
            references.add(node.attr)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "cfg"
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value in BATCH_FIELDS
        ):
            references.add(node.args[1].value)
    return references


def _has_nested_batch_access(tree: ast.Module) -> bool:
    return any(
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Attribute)
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "cfg"
        and node.value.attr == "batch"
        for node in ast.walk(tree)
    )


def test_current_batch_flat_facade_is_exact_and_constructor_compatible() -> None:
    fields = dataclasses.fields(TTSConfig)
    field_names = tuple(field.name for field in fields)
    field_by_name = {field.name: field for field in fields}
    annotations = get_type_hints(TTSConfig)

    assert len(fields) == 179
    assert sum(field.init for field in fields) == 177
    assert tuple(field.name for field in fields if not field.init) == (
        "_voices_cache",
        "_voices_cache_signature",
    )
    start = field_names.index(BATCH_FIELDS[0])
    assert field_names[start : start + len(BATCH_FIELDS)] == BATCH_FIELDS
    assert "batch" not in field_by_name

    for key, annotation, default, _env_name, _declaration_key in EXPECTED_BATCH:
        assert annotations[key] is annotation
        assert field_by_name[key].default == default
        assert field_by_name[key].init is True

    configured = TTSConfig(
        batch_enabled=False,
        batch_max_items=7,
        batch_concurrency=3,
    )
    assert (
        configured.batch_enabled,
        configured.batch_max_items,
        configured.batch_concurrency,
    ) == (False, 7, 3)


def test_current_batch_integer_env_owner_and_bool_mapping_are_preserved() -> None:
    declarations = config_env_domain.BATCH_INT_DECLARATIONS
    assert tuple(
        (item.env_name, item.attr, item.min_value, item.max_value)
        for item in declarations
    ) == EXPECTED_INT_ENV
    assert config_env.BATCH_INT_DECLARATIONS is declarations

    for declaration in declarations:
        spec = config_env.INT_ENV[declaration.env_name]
        assert (spec.attr, spec.min_value, spec.max_value) == (
            declaration.attr,
            declaration.min_value,
            declaration.max_value,
        )
    assert config_env.BOOL_ENV["KOKORO_BATCH_ENABLED"] == "batch_enabled"


def test_current_batch_env_behavior_preserves_defaults_and_lower_bounds(
    monkeypatch,
) -> None:
    isolated_env: dict[str, str] = {}
    monkeypatch.setattr(config_env.os, "environ", isolated_env)

    defaults = TTSConfig()
    config_env.apply_env(defaults)
    assert (
        defaults.batch_enabled,
        defaults.batch_max_items,
        defaults.batch_concurrency,
    ) == (True, 20, 1)

    isolated_env["KOKORO_BATCH_ENABLED"] = "false"
    isolated_env["KOKORO_BATCH_MAX_ITEMS"] = "0"
    isolated_env["KOKORO_BATCH_CONCURRENCY"] = "-7"
    bounded = TTSConfig()
    config_env.apply_env(bounded)
    assert (
        bounded.batch_enabled,
        bounded.batch_max_items,
        bounded.batch_concurrency,
    ) == (False, 1, 1)

    isolated_env["KOKORO_BATCH_ENABLED"] = "YES"
    isolated_env["KOKORO_BATCH_MAX_ITEMS"] = "8"
    isolated_env["KOKORO_BATCH_CONCURRENCY"] = "4"
    configured = TTSConfig()
    config_env.apply_env(configured)
    assert (
        configured.batch_enabled,
        configured.batch_max_items,
        configured.batch_concurrency,
    ) == (True, 8, 4)


def test_current_batch_worker_exports_are_exact() -> None:
    from kokoro_tts.server import _WORKER_ENV_EXPORTS

    assert {
        env_name: attr
        for env_name, attr in _WORKER_ENV_EXPORTS.items()
        if attr in BATCH_FIELDS
    } == EXPECTED_WORKER_EXPORTS


def test_current_batch_admin_runtime_absence_and_non_ownership(tmp_path) -> None:
    assert not set(BATCH_FIELDS).intersection(ADMIN_CONFIG_FIELDS)

    runtime_file = tmp_path / "runtime-config.json"
    with runtime_file.open("w", encoding="utf-8") as runtime_stream:
        runtime_stream.write(
            '{"values":{"batch_enabled":false,"batch_max_items":99,'
            '"batch_concurrency":9}}'
        )
    config = TTSConfig(
        batch_enabled=True,
        batch_max_items=7,
        batch_concurrency=3,
        runtime_config_file=runtime_file,
    )
    load_runtime_config(config)
    assert (
        config.batch_enabled,
        config.batch_max_items,
        config.batch_concurrency,
    ) == (True, 7, 3)


def test_current_batch_consumers_remain_on_the_flat_facade() -> None:
    package_root = Path(config_module.__file__).parent
    service_tree = ast.parse(
        (package_root / "service_extras.py").read_text(encoding="utf-8")
    )
    health_tree = ast.parse(
        (package_root / "routes/status_parts/health.py").read_text(encoding="utf-8")
    )
    models_tree = ast.parse(
        (package_root / "routes/status_parts/models.py").read_text(encoding="utf-8")
    )

    assert _flat_batch_references(service_tree) == set(BATCH_FIELDS)
    assert "batch_enabled" in _flat_batch_references(health_tree)
    assert "batch_enabled" in _flat_batch_references(models_tree)
    assert not any(
        _has_nested_batch_access(tree)
        for tree in (service_tree, health_tree, models_tree)
    )


def test_future_batch_declaration_owner_is_immutable_and_reuses_env_identity() -> None:
    module_name = "kokoro_tts.batch_config_metadata"
    assert importlib.util.find_spec(module_name) is not None, (
        "future Batch ownership requires batch_config_metadata.py with "
        "BATCH_CONFIG_METADATA"
    )
    module = importlib.import_module(module_name)
    assert hasattr(module, "BATCH_CONFIG_METADATA")
    metadata = module.BATCH_CONFIG_METADATA
    assert isinstance(metadata, tuple)
    assert tuple(item.key for item in metadata) == BATCH_FIELDS

    declarations = {
        item.attr: item for item in config_env_domain.BATCH_INT_DECLARATIONS
    }
    for item, expected in zip(metadata, EXPECTED_BATCH):
        key, annotation, default, env_name, declaration_key = expected
        assert dataclasses.is_dataclass(item)
        assert getattr(type(item), "__dataclass_params__").frozen is True
        assert (item.key, item.annotation, item.default, item.env_name) == (
            key,
            annotation,
            default,
            env_name,
        )
        if declaration_key is None:
            assert item.env_declaration is None
            assert config_env.BOOL_ENV[item.env_name] == item.key
        else:
            assert item.env_declaration is declarations[declaration_key]
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError, TypeError)):
            item.default = object()


def test_future_batch_ttsconfig_defaults_depend_on_declaration_owner() -> None:
    tree = _module_tree(config_module)
    owner_bindings = _batch_owner_import_bindings(tree)
    assert owner_bindings, (
        "TTSConfig must import the Batch declaration owner; adding a dead "
        "BATCH_CONFIG_METADATA tuple is insufficient"
    )
    definitions = _top_level_definitions(tree)
    assignments = _ttsconfig_assignments(tree)

    for field_name in BATCH_FIELDS:
        value = assignments[field_name].value
        assert value is not None
        assert _depends_on_batch_owner(
            value,
            owner_bindings=owner_bindings,
            definitions=definitions,
        ), f"TTSConfig.{field_name} must derive its default from the Batch owner"
