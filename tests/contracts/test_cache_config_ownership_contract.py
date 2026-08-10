"""Cache configuration ownership contracts.

Current-characterization tests freeze the public flat facade and its existing
ENV/Admin/runtime behavior.  The final test is intentionally RED until the
declaration-only Cache owner is implemented in production.
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
import importlib.util
import inspect
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from kokoro_tts import config_env
from kokoro_tts.admin_config.schema import (
    ADMIN_CONFIG_FIELDS,
    validate_admin_config_values,
)
from kokoro_tts.config import TTSConfig, load_config
from kokoro_tts.config_env_domain import CACHE_INT_DECLARATIONS


pytestmark = pytest.mark.contract


CACHE_KEYS = (
    "cache_enabled",
    "cache_max_items",
    "cache_max_bytes",
    "cache_skip_text_over_chars",
    "cache_skip_audio_over_bytes",
)

EXPECTED_FACADE = (
    ("cache_enabled", bool, True),
    ("cache_max_items", int, 64),
    ("cache_max_bytes", int, 512 * 1024 * 1024),
    ("cache_skip_text_over_chars", int, 1200),
    ("cache_skip_audio_over_bytes", int, 20 * 1024 * 1024),
)

EXPECTED_ENV = (
    ("cache_enabled", "KOKORO_CACHE_ENABLED", None),
    ("cache_max_items", "KOKORO_CACHE_MAX_ITEMS", (0, None)),
    ("cache_max_bytes", "KOKORO_CACHE_MAX_BYTES", (0, None)),
    (
        "cache_skip_text_over_chars",
        "KOKORO_CACHE_SKIP_TEXT_OVER_CHARS",
        (0, None),
    ),
    (
        "cache_skip_audio_over_bytes",
        "KOKORO_CACHE_SKIP_AUDIO_OVER_BYTES",
        (0, None),
    ),
)

# cache_enabled is an ENV/facade field, but is not currently Admin-writable.
EXPECTED_ADMIN = (
    (
        "cache_max_items",
        "KOKORO_CACHE_MAX_ITEMS",
        "service",
        "int",
        64,
        0,
        2000,
        1,
        False,
        False,
        False,
    ),
    (
        "cache_max_bytes",
        "KOKORO_CACHE_MAX_BYTES",
        "service",
        "int",
        512 * 1024 * 1024,
        0,
        8 * 1024 * 1024 * 1024,
        1024 * 1024,
        False,
        False,
        False,
    ),
    (
        "cache_skip_text_over_chars",
        "KOKORO_CACHE_SKIP_TEXT_OVER_CHARS",
        "service",
        "int",
        1200,
        0,
        100000,
        100,
        False,
        False,
        False,
    ),
    (
        "cache_skip_audio_over_bytes",
        "KOKORO_CACHE_SKIP_AUDIO_OVER_BYTES",
        "service",
        "int",
        20 * 1024 * 1024,
        0,
        2147483647,
        1024 * 1024,
        False,
        False,
        False,
    ),
)

FUTURE_OWNER_MODULE = "kokoro_tts.cache_config_metadata"


def _admin_row(field) -> tuple[object, ...]:
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
        field.rebuild_moss,
        field.advanced,
    )


def _owner_import_bindings(tree: ast.Module) -> set[str]:
    """Return local names imported from the future Cache owner module."""

    bindings: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.endswith("cache_config_metadata"):
                bindings.update(alias.asname or alias.name for alias in node.names)
            elif any(alias.name == "cache_config_metadata" for alias in node.names):
                bindings.update(
                    alias.asname or alias.name
                    for alias in node.names
                    if alias.name == "cache_config_metadata"
                )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == FUTURE_OWNER_MODULE:
                    bindings.add(alias.asname or alias.name.split(".")[0])
    return bindings


def _module_symbol_definitions(tree: ast.Module) -> dict[str, ast.AST]:
    definitions: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    definitions[target.id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.value is not None:
                definitions[node.target.id] = node.value
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            definitions[node.name] = node
    return definitions


def _depends_on_owner(
    expression: ast.AST,
    owner_bindings: set[str],
    definitions: dict[str, ast.AST],
    seen: set[str] | None = None,
) -> bool:
    seen = set() if seen is None else seen
    names = {node.id for node in ast.walk(expression) if isinstance(node, ast.Name)}
    if names & owner_bindings:
        return True
    for name in names - seen:
        definition = definitions.get(name)
        if definition is None:
            continue
        if _depends_on_owner(
            definition,
            owner_bindings,
            definitions,
            seen | {name},
        ):
            return True
    return False


def _assignment_value(tree: ast.Module, name: str) -> ast.AST:
    definitions = _module_symbol_definitions(tree)
    assert name in definitions, f"missing module declaration: {name}"
    return definitions[name]


def test_cache_flat_ttsconfig_surface_order_types_defaults_and_constructor(
    tmp_path: Path,
) -> None:
    selected = tuple(
        (field.name, field.type, field.default)
        for field in dataclasses.fields(TTSConfig)
        if field.name in CACHE_KEYS
    )
    assert selected == EXPECTED_FACADE

    configured = TTSConfig(
        model_dir=tmp_path / "models",
        cache_enabled=False,
        cache_max_items=3,
        cache_max_bytes=4,
        cache_skip_text_over_chars=5,
        cache_skip_audio_over_bytes=6,
    )
    assert tuple(getattr(configured, key) for key in CACHE_KEYS) == (
        False,
        3,
        4,
        5,
        6,
    )
    assert not hasattr(configured, "cache")


def test_cache_env_declaration_identity_and_projection_are_exact() -> None:
    integer_rows = tuple(
        (
            declaration.attr,
            declaration.env_name,
            (declaration.min_value, declaration.max_value),
        )
        for declaration in CACHE_INT_DECLARATIONS
    )
    assert integer_rows == EXPECTED_ENV[1:]
    assert config_env.BOOL_ENV["KOKORO_CACHE_ENABLED"] == "cache_enabled"

    for declaration in CACHE_INT_DECLARATIONS:
        spec = config_env.INT_ENV[declaration.env_name]
        assert (spec.attr, spec.min_value, spec.max_value) == (
            declaration.attr,
            declaration.min_value,
            declaration.max_value,
        )

    source_tree = ast.parse(Path(config_env.__file__).read_text(encoding="utf-8"))
    declaration_comprehensions = [
        node
        for node in ast.walk(source_tree)
        if isinstance(node, ast.comprehension)
        and isinstance(node.iter, ast.Name)
        and node.iter.id == "CACHE_INT_DECLARATIONS"
    ]
    assert len(declaration_comprehensions) == 1


def test_cache_env_parsing_and_clamping_are_hermetic(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    environment = {
        "KOKORO_CACHE_ENABLED": " false ",
        "KOKORO_CACHE_MAX_ITEMS": "-9",
        "KOKORO_CACHE_MAX_BYTES": " 1048576 ",
        "KOKORO_CACHE_SKIP_TEXT_OVER_CHARS": "not-an-int",
        "KOKORO_CACHE_SKIP_AUDIO_OVER_BYTES": "+20971521",
    }
    monkeypatch.setattr(config_env.os, "environ", environment)
    config = SimpleNamespace(
        output_dir=tmp_path / "outputs",
        credentials_dir=tmp_path / "credentials",
        api_key_file=tmp_path / "credentials" / "api-key",
        admin_credentials_file=tmp_path / "credentials" / "admin.json",
        runtime_config_file=tmp_path / "runtime.json",
        cache_enabled=True,
        cache_max_items=64,
        cache_max_bytes=512 * 1024 * 1024,
        cache_skip_text_over_chars=1200,
        cache_skip_audio_over_bytes=20 * 1024 * 1024,
    )

    with caplog.at_level(logging.WARNING, logger="kokoro_tts.config_env"):
        config_env.apply_env(config)

    assert tuple(getattr(config, key) for key in CACHE_KEYS) == (
        False,
        0,
        1024 * 1024,
        1200,
        20971521,
    )
    assert len(caplog.records) == 1
    assert "KOKORO_CACHE_SKIP_TEXT_OVER_CHARS" in caplog.records[0].getMessage()


def test_cache_admin_metadata_and_runtime_allowlist_match_current_surface() -> None:
    admin_keys = tuple(key for key in ADMIN_CONFIG_FIELDS if key in CACHE_KEYS)
    assert admin_keys == tuple(row[0] for row in EXPECTED_ADMIN)
    assert tuple(_admin_row(ADMIN_CONFIG_FIELDS[key]) for key in admin_keys) == (
        EXPECTED_ADMIN
    )

    assert "cache_enabled" not in ADMIN_CONFIG_FIELDS
    assert validate_admin_config_values(
        {
            "cache_max_items": "7",
            "cache_max_bytes": "1048576",
            "cache_skip_text_over_chars": "0",
            "cache_skip_audio_over_bytes": "20971520",
        }
    ) == {
        "cache_max_items": 7,
        "cache_max_bytes": 1048576,
        "cache_skip_text_over_chars": 0,
        "cache_skip_audio_over_bytes": 20971520,
    }
    with pytest.raises(KeyError, match="cache_enabled"):
        validate_admin_config_values({"cache_enabled": False})


def test_cache_precedence_and_consumers_keep_the_flat_facade() -> None:
    load_tree = ast.parse(inspect.getsource(load_config))
    function = load_tree.body[0]
    assert isinstance(function, ast.FunctionDef)

    calls = [node for node in ast.walk(function) if isinstance(node, ast.Call)]

    def call_line(name: str) -> int:
        matches = [
            node.lineno
            for node in calls
            if isinstance(node.func, ast.Name) and node.func.id == name
        ]
        assert len(matches) == 1
        return matches[0]

    kwargs_loops = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.For)
        and isinstance(node.iter, ast.Call)
        and isinstance(node.iter.func, ast.Attribute)
        and isinstance(node.iter.func.value, ast.Name)
        and node.iter.func.value.id == "kwargs"
        and node.iter.func.attr == "items"
    ]
    assert len(kwargs_loops) == 1
    kwargs_loop = kwargs_loops[0]
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "setattr"
        for node in ast.walk(kwargs_loop)
    )

    validation_lines = [
        node.lineno
        for node in calls
        if isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "config"
        and node.func.attr == "validate_security"
    ]
    assert len(validation_lines) == 1
    assert (
        call_line("TTSConfig")
        < call_line("apply_env")
        < call_line("load_runtime_config")
        < kwargs_loop.lineno
        < validation_lines[0]
    )

    consumer_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "kokoro_tts"
        / "services"
        / "state_parts"
        / "cache_state.py"
    )
    consumer_source = consumer_path.read_text(encoding="utf-8")
    assert "self.cfg.cache_enabled" in consumer_source
    assert "self.cfg.cache_max_items" in consumer_source
    for key in CACHE_KEYS[2:]:
        assert f'getattr(self.cfg, "{key}"' in consumer_source


def test_future_cache_declaration_owner_projects_frozen_surfaces() -> None:
    spec = importlib.util.find_spec(FUTURE_OWNER_MODULE)
    assert spec is not None, (
        "missing declaration-only Cache owner: expected "
        f"{FUTURE_OWNER_MODULE}.CACHE_CONFIG_METADATA"
    )

    module = importlib.import_module(FUTURE_OWNER_MODULE)
    metadata = module.CACHE_CONFIG_METADATA
    assert isinstance(metadata, tuple)
    assert tuple(item.key for item in metadata) == CACHE_KEYS
    assert tuple((item.key, item.annotation, item.default) for item in metadata) == (
        EXPECTED_FACADE
    )

    env_by_key = {key: (env_name, limits) for key, env_name, limits in EXPECTED_ENV}
    declarations_by_key = {
        declaration.attr: declaration for declaration in CACHE_INT_DECLARATIONS
    }
    for item in metadata:
        env_name, limits = env_by_key[item.key]
        assert item.env_name == env_name
        if limits is None:
            assert item.env_declaration is None
        else:
            assert item.env_declaration is declarations_by_key[item.key]

    admin_by_key = {row[0]: row for row in EXPECTED_ADMIN}
    for item in metadata:
        if item.key == "cache_enabled":
            assert item.admin is None
            continue
        admin = item.admin
        expected = admin_by_key[item.key]
        assert (
            item.key,
            item.env_name,
            admin.group,
            admin.type,
            item.default,
            admin.min_value,
            admin.max_value,
            admin.step,
            admin.restart,
            admin.rebuild_moss,
            admin.advanced,
        ) == expected

    declaration_type = type(metadata[0])
    assert dataclasses.is_dataclass(declaration_type)
    assert declaration_type.__dataclass_params__.frozen is True
    with pytest.raises(dataclasses.FrozenInstanceError):
        metadata[0].default = False

    admin_projection = metadata[1].admin
    assert dataclasses.is_dataclass(type(admin_projection))
    assert type(admin_projection).__dataclass_params__.frozen is True
    with pytest.raises(dataclasses.FrozenInstanceError):
        admin_projection.step = 2

    source_path = Path(module.__file__).resolve()
    source_tree = ast.parse(source_path.read_text(encoding="utf-8"))
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
    forbidden_import_tokens = (
        "admin_config",
        "engine",
        "http",
        "model_sources",
        "os",
        "pathlib",
        "requests",
        "runtime",
        "server",
        "service",
        "socket",
        "subprocess",
        "urllib",
        "worker",
    )
    assert not any(
        token in imported.lower()
        for imported in imported_modules
        for token in forbidden_import_tokens
    )
    assert not any(
        imported.lower() == "config" or imported.lower().endswith(".config")
        for imported in imported_modules
    )
    forbidden_calls = {
        "create_app",
        "load_runtime_config",
        "open",
        "read_bytes",
        "read_text",
        "request",
        "urlopen",
    }
    assert not any(
        isinstance(node, ast.Call)
        and (
            isinstance(node.func, ast.Name)
            and node.func.id in forbidden_calls
            or isinstance(node.func, ast.Attribute)
            and node.func.attr in forbidden_calls
        )
        for node in ast.walk(source_tree)
    )


def test_future_ttsconfig_cache_defaults_are_consumed_from_owner() -> None:
    source_path = Path(inspect.getsourcefile(TTSConfig) or "")
    source_tree = ast.parse(source_path.read_text(encoding="utf-8"))
    owner_bindings = _owner_import_bindings(source_tree)
    assert owner_bindings, (
        "config.py must import the Cache declaration owner; an unused metadata "
        "module is not an ownership migration"
    )
    definitions = _module_symbol_definitions(source_tree)
    classes = [
        node
        for node in source_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "TTSConfig"
    ]
    assert len(classes) == 1
    cache_defaults = {
        node.target.id: node.value
        for node in classes[0].body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id in CACHE_KEYS
    }
    assert tuple(cache_defaults) == CACHE_KEYS
    assert all(value is not None for value in cache_defaults.values())
    assert all(
        _depends_on_owner(value, owner_bindings, definitions)
        for value in cache_defaults.values()
        if value is not None
    ), "all five flat TTSConfig Cache defaults must derive from the owner"


def test_future_admin_cache_rows_are_consumed_from_same_owner() -> None:
    source_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "kokoro_tts"
        / "admin_config"
        / "groups"
        / "cache.py"
    )
    source_tree = ast.parse(source_path.read_text(encoding="utf-8"))
    owner_bindings = _owner_import_bindings(source_tree)
    assert owner_bindings, (
        "admin_config/groups/cache.py must import the Cache declaration owner; "
        "an unused metadata module is not an Admin ownership migration"
    )
    definitions = _module_symbol_definitions(source_tree)
    fields_expression = _assignment_value(source_tree, "FIELDS")
    assert _depends_on_owner(fields_expression, owner_bindings, definitions), (
        "Admin FIELDS must project the four writable Cache rows from the same "
        "declaration owner"
    )

    directly_hardcoded_keys: set[str] = set()
    for node in ast.walk(source_tree):
        if not isinstance(node, ast.Call):
            continue
        function_name = None
        if isinstance(node.func, ast.Name):
            function_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            function_name = node.func.attr
        if function_name not in {"AdminConfigField", "field_def"}:
            continue
        candidates = list(node.args[:1])
        candidates.extend(
            keyword.value for keyword in node.keywords if keyword.arg == "key"
        )
        directly_hardcoded_keys.update(
            candidate.value
            for candidate in candidates
            if isinstance(candidate, ast.Constant)
            and isinstance(candidate.value, str)
            and candidate.value in CACHE_KEYS
        )
    assert not directly_hardcoded_keys, (
        "matching Admin Cache rows remain independently hard-coded: "
        f"{sorted(directly_hardcoded_keys)}"
    )
