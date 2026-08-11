"""Update Check configuration ownership contracts.

Current-state tests freeze the four-field flat facade and its existing ENV,
worker, runtime, and consumer boundaries. Future-state tests intentionally stay
red until a declaration-only owner exists and ``TTSConfig`` consumes it.
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
import importlib.util
import json
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import get_type_hints

import pytest

from kokoro_tts import config as config_module
from kokoro_tts import config_env, config_env_domain
from kokoro_tts.admin_config import ADMIN_CONFIG_FIELDS
from kokoro_tts.config import TTSConfig
from kokoro_tts.update_checker import UpdateChecker


UPDATE_CHECK_FIELDS = (
    "update_check_enabled",
    "update_repository",
    "update_check_timeout_seconds",
    "update_check_cache_seconds",
)

EXPECTED_FACADE = (
    ("update_check_enabled", bool, True),
    ("update_repository", str, "angevox/AngeVoice"),
    ("update_check_timeout_seconds", float, 3.0),
    ("update_check_cache_seconds", float, 21600.0),
)

EXPECTED_ENV = (
    (
        "ANGEVOICE_UPDATE_CHECK_ENABLED",
        "update_check_enabled",
        "bool",
        None,
        None,
    ),
    (
        "ANGEVOICE_UPDATE_REPOSITORY",
        "update_repository",
        "str",
        None,
        None,
    ),
    (
        "ANGEVOICE_UPDATE_CHECK_TIMEOUT_SECONDS",
        "update_check_timeout_seconds",
        "float",
        0.2,
        10.0,
    ),
    (
        "ANGEVOICE_UPDATE_CHECK_CACHE_SECONDS",
        "update_check_cache_seconds",
        "float",
        0.0,
        604800.0,
    ),
)

EXPECTED_WORKER_EXPORTS = {
    env_name: field_name
    for env_name, field_name, _family, _minimum, _maximum in EXPECTED_ENV
}

FUTURE_OWNER_MODULE = "kokoro_tts.update_check_config_metadata"


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
        ).endswith("update_check_config_metadata"):
            bindings.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            bindings.update(
                alias.asname or alias.name.split(".")[-1]
                for alias in node.names
                if alias.name.endswith(".update_check_config_metadata")
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


def test_current_update_check_flat_facade_is_exact_and_compatible() -> None:
    fields = dataclasses.fields(TTSConfig)
    names = tuple(field.name for field in fields)
    by_name = {field.name: field for field in fields}
    annotations = get_type_hints(TTSConfig)

    assert (len(fields), sum(field.init for field in fields)) == (179, 177)
    assert tuple(field.name for field in fields if not field.init) == (
        "_voices_cache",
        "_voices_cache_signature",
    )
    start = names.index(UPDATE_CHECK_FIELDS[0])
    assert names[start : start + len(UPDATE_CHECK_FIELDS)] == UPDATE_CHECK_FIELDS
    assert "update_check" not in by_name

    for key, annotation, default in EXPECTED_FACADE:
        assert annotations[key] is annotation
        assert by_name[key].default == default
        assert by_name[key].init is True

    configured = TTSConfig(
        update_check_enabled=False,
        update_repository="owner/repository",
        update_check_timeout_seconds=0.75,
        update_check_cache_seconds=42.0,
    )
    assert tuple(getattr(configured, key) for key in UPDATE_CHECK_FIELDS) == (
        False,
        "owner/repository",
        0.75,
        42.0,
    )


def test_current_update_check_env_owner_identity_and_projections_are_exact() -> None:
    declarations = config_env_domain.UPDATE_CHECK_ENV_DECLARATIONS
    assert config_env.UPDATE_CHECK_ENV_DECLARATIONS is declarations
    assert tuple(
        (
            item.env_name,
            item.attr,
            item.family,
            item.min_value,
            item.max_value,
        )
        for item in declarations
    ) == EXPECTED_ENV

    projected_env_names: dict[str, list[str]] = {
        key: [] for key in UPDATE_CHECK_FIELDS
    }
    for env_name, attr in config_env.STR_ENV.items():
        if attr in projected_env_names:
            projected_env_names[attr].append(env_name)
    for env_name, spec in config_env.FLOAT_ENV.items():
        if spec.attr in projected_env_names:
            projected_env_names[spec.attr].append(env_name)
    for env_name, attr in config_env.BOOL_ENV.items():
        if attr in projected_env_names:
            projected_env_names[attr].append(env_name)
    assert projected_env_names == {
        field_name: [env_name]
        for env_name, field_name, _family, _minimum, _maximum in EXPECTED_ENV
    }

    for declaration in declarations:
        if declaration.family == "str":
            assert config_env.STR_ENV[declaration.env_name] == declaration.attr
        elif declaration.family == "bool":
            assert config_env.BOOL_ENV[declaration.env_name] == declaration.attr
        else:
            spec = config_env.FLOAT_ENV[declaration.env_name]
            assert (spec.attr, spec.min_value, spec.max_value) == (
                declaration.attr,
                declaration.min_value,
                declaration.max_value,
            )

    from kokoro_tts import server

    assert server.UPDATE_CHECK_ENV_DECLARATIONS is declarations
    assert {
        env_name: attr
        for env_name, attr in server._WORKER_ENV_EXPORTS.items()
        if attr in UPDATE_CHECK_FIELDS
    } == EXPECTED_WORKER_EXPORTS


def test_current_update_check_env_behavior_and_precedence_are_hermetic(
    monkeypatch, tmp_path
) -> None:
    runtime_file = tmp_path / "runtime-config.json"
    with runtime_file.open("w", encoding="utf-8") as runtime_stream:
        runtime_stream.write(
            json.dumps(
                {
                    "values": {
                        "update_check_enabled": True,
                        "update_repository": "runtime/repository",
                        "update_check_timeout_seconds": 9.0,
                        "update_check_cache_seconds": 9.0,
                    }
                }
            )
        )
    isolated_env = {
        "ANGEVOICE_RUNTIME_CONFIG_FILE": str(runtime_file),
        "ANGEVOICE_UPDATE_CHECK_ENABLED": "false",
        "ANGEVOICE_UPDATE_REPOSITORY": " env/repository ",
        "ANGEVOICE_UPDATE_CHECK_TIMEOUT_SECONDS": "-7",
        "ANGEVOICE_UPDATE_CHECK_CACHE_SECONDS": "999999",
    }
    monkeypatch.setattr(config_env.os, "environ", isolated_env)

    from_env = config_module.load_config()
    assert tuple(getattr(from_env, key) for key in UPDATE_CHECK_FIELDS) == (
        False,
        " env/repository ",
        0.2,
        604800.0,
    )

    explicit = config_module.load_config(
        update_check_enabled=True,
        update_repository="explicit/repository",
        update_check_timeout_seconds=1.25,
        update_check_cache_seconds=60.0,
    )
    assert tuple(getattr(explicit, key) for key in UPDATE_CHECK_FIELDS) == (
        True,
        "explicit/repository",
        1.25,
        60.0,
    )


def test_current_update_check_admin_runtime_projection_remains_absent(
    tmp_path,
) -> None:
    assert not set(UPDATE_CHECK_FIELDS).intersection(ADMIN_CONFIG_FIELDS)

    runtime_file = tmp_path / "runtime-config.json"
    with runtime_file.open("w", encoding="utf-8") as runtime_stream:
        runtime_stream.write(
            '{"values":{"update_check_enabled":false,'
            '"update_repository":"runtime/repository",'
            '"update_check_timeout_seconds":9.0,'
            '"update_check_cache_seconds":9.0}}'
        )
    config = TTSConfig(
        update_check_enabled=True,
        update_repository="owner/repository",
        update_check_timeout_seconds=1.0,
        update_check_cache_seconds=60.0,
        runtime_config_file=runtime_file,
    )
    from kokoro_tts.admin_config import load_runtime_config

    load_runtime_config(config)
    assert tuple(getattr(config, key) for key in UPDATE_CHECK_FIELDS) == (
        True,
        "owner/repository",
        1.0,
        60.0,
    )


def test_current_update_checker_keeps_flat_config_and_injected_opener_boundary() -> None:
    calls: list[tuple[object, float]] = []

    class Response:
        def read(self) -> bytes:
            return b'{"tag_name":"v999.0.0","name":"Future release"}'

    def opener(request, *, timeout):  # noqa: ANN001, ANN202
        calls.append((request, timeout))
        return Response()

    configured = SimpleNamespace(
        update_check_enabled=True,
        update_repository="owner/repository",
        update_check_timeout_seconds=0.75,
        update_check_cache_seconds=42.0,
    )
    checker = UpdateChecker(configured, opener=opener)
    result = checker.check(force=True)
    request, timeout = calls.pop()
    assert checker.cfg is configured
    assert result["repository"] == "owner/repository"
    assert result["update_available"] is True
    assert result["auto_update"] is False
    assert request.full_url.endswith("/repos/owner/repository/releases/latest")
    assert timeout == 0.75

    fallback_checker = UpdateChecker(SimpleNamespace(), opener=opener)
    fallback = fallback_checker.check(force=True)
    request, timeout = calls.pop()
    assert fallback["enabled"] is True
    assert fallback["repository"] == "angevox/AngeVoice"
    assert fallback_checker._cache_seconds == 21600.0
    assert request.full_url.endswith("/repos/angevox/AngeVoice/releases/latest")
    assert timeout == 3.0


def test_future_update_check_declaration_owner_is_immutable_and_reuses_env_identity(
) -> None:
    spec = importlib.util.find_spec(FUTURE_OWNER_MODULE)
    assert spec is not None, (
        "missing declaration-only Update Check owner: expected "
        f"{FUTURE_OWNER_MODULE}.UPDATE_CHECK_CONFIG_METADATA"
    )
    module = importlib.import_module(FUTURE_OWNER_MODULE)
    metadata = module.UPDATE_CHECK_CONFIG_METADATA
    by_key = module.UPDATE_CHECK_CONFIG_BY_KEY

    assert isinstance(metadata, tuple)
    assert tuple(item.key for item in metadata) == UPDATE_CHECK_FIELDS
    assert tuple(
        (item.key, item.annotation, item.default) for item in metadata
    ) == EXPECTED_FACADE
    assert isinstance(by_key, MappingProxyType)
    assert tuple(by_key) == UPDATE_CHECK_FIELDS
    assert all(by_key[item.key] is item for item in metadata)

    declarations = {
        item.attr: item
        for item in config_env_domain.UPDATE_CHECK_ENV_DECLARATIONS
    }
    for item in metadata:
        assert dataclasses.is_dataclass(item)
        assert type(item).__dataclass_params__.frozen is True
        assert tuple(field.name for field in dataclasses.fields(item)) == (
            "key",
            "annotation",
            "default",
            "env_declaration",
        )
        assert item.env_declaration is declarations[item.key]
        with pytest.raises(
            (dataclasses.FrozenInstanceError, AttributeError, TypeError)
        ):
            item.default = object()

    source_tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    imported_modules = {
        node.module or ""
        for node in source_tree.body
        if isinstance(node, ast.ImportFrom)
    }
    imported_modules.update(
        alias.name
        for node in source_tree.body
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    forbidden_tokens = (
        "admin_config",
        "http",
        "pathlib",
        "requests",
        "routes",
        "server",
        "socket",
        "subprocess",
        "update_checker",
        "urllib",
        "worker",
    )
    assert not any(
        token in imported.lower()
        for imported in imported_modules
        for token in forbidden_tokens
    )
    assert not any(
        imported.lower() == "config" or imported.lower().endswith(".config")
        for imported in imported_modules
    )


def test_future_update_check_ttsconfig_defaults_depend_on_owner() -> None:
    tree = _module_tree(config_module)
    owner_bindings = _owner_import_bindings(tree)
    assert owner_bindings, (
        "TTSConfig must import the Update Check declaration owner; adding a "
        "dead UPDATE_CHECK_CONFIG_METADATA tuple is insufficient"
    )
    definitions = _top_level_definitions(tree)
    assignments = _ttsconfig_assignments(tree)

    for field_name in UPDATE_CHECK_FIELDS:
        value = assignments[field_name].value
        assert value is not None
        assert _depends_on_owner(
            value,
            owner_bindings=owner_bindings,
            definitions=definitions,
        ), (
            f"TTSConfig.{field_name} must derive its default from the "
            "Update Check owner"
        )
