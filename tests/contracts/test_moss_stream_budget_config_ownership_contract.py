"""MOSS stream-budget declaration/default ownership contract freeze.

These tests characterize the four-field flat ``TTSConfig`` facade and preserve
the declaration/default, runtime-reader, ENV, worker, Admin, and pure-helper
ownership boundaries established by P2-001.

Streaming algorithms, waveform splitting, ENV validation, worker propagation,
and Admin ownership are explicitly outside this P2-001 contract.
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
from kokoro_tts import config_env, moss_engine_streaming, server
from kokoro_tts.admin_config import ADMIN_CONFIG_FIELDS
from kokoro_tts.config import TTSConfig
from kokoro_tts.moss_runtime import audio as moss_runtime_audio
from kokoro_tts.moss_runtime import streaming as moss_runtime_streaming


pytestmark = pytest.mark.contract

MOSS_STREAM_BUDGET_FIELDS = (
    "moss_stream_budget_threshold_low",
    "moss_stream_budget_threshold_mid",
    "moss_stream_budget_threshold_high",
    "moss_stream_chunk_min_floor",
)

EXPECTED_FACADE = (
    ("moss_stream_budget_threshold_low", float, 0.25),
    ("moss_stream_budget_threshold_mid", float, 0.65),
    ("moss_stream_budget_threshold_high", float, 1.20),
    ("moss_stream_chunk_min_floor", float, 0.10),
)

EXPECTED_ENV = {
    "MOSS_STREAM_BUDGET_THRESHOLD_LOW": (
        "moss_stream_budget_threshold_low",
        0.0,
        None,
    ),
    "MOSS_STREAM_BUDGET_THRESHOLD_MID": (
        "moss_stream_budget_threshold_mid",
        0.0,
        None,
    ),
    "MOSS_STREAM_BUDGET_THRESHOLD_HIGH": (
        "moss_stream_budget_threshold_high",
        0.0,
        None,
    ),
    "MOSS_STREAM_CHUNK_MIN_FLOOR": (
        "moss_stream_chunk_min_floor",
        0.01,
        None,
    ),
}

EXPECTED_WORKER_EXPORTS = {
    env_name: values[0] for env_name, values in EXPECTED_ENV.items()
}

EXCLUDED_NEARBY_FIELDS = {
    "moss_realtime_streaming_decode",
    "moss_segment_length",
    "moss_stream_chunk_seconds",
    "moss_stream_prebuffer_seconds",
    "moss_stream_queue_max_items",
}

FUTURE_OWNER_MODULE = "kokoro_tts.moss_stream_budget_config_metadata"
FUTURE_OWNER_TYPE = "MossStreamBudgetConfigMetadata"
FUTURE_METADATA_SYMBOL = "MOSS_STREAM_BUDGET_CONFIG_METADATA"
FUTURE_BY_KEY_SYMBOL = "MOSS_STREAM_BUDGET_CONFIG_BY_KEY"


def _module_tree(module) -> ast.Module:  # noqa: ANN001
    return ast.parse(Path(module.__file__).read_text(encoding="utf-8"))


def _definition(tree: ast.AST, name: str) -> ast.AST:
    return next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and node.name == name
    )


def _ttsconfig_assignments(tree: ast.Module) -> dict[str, ast.AnnAssign]:
    config_class = _definition(tree, "TTSConfig")
    assert isinstance(config_class, ast.ClassDef)
    return {
        node.target.id: node
        for node in config_class.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }


def _field_bound_getattr_calls(node: ast.AST) -> dict[str, ast.Call]:
    calls: dict[str, ast.Call] = {}
    for item in ast.walk(node):
        if not (
            isinstance(item, ast.Call)
            and isinstance(item.func, ast.Name)
            and item.func.id == "getattr"
            and len(item.args) >= 3
            and isinstance(item.args[1], ast.Constant)
            and item.args[1].value in MOSS_STREAM_BUDGET_FIELDS
        ):
            continue
        field = str(item.args[1].value)
        assert field not in calls, f"duplicate runtime read for {field}"
        calls[field] = item
    return calls


def _canonical_owner_default_key(node: ast.AST) -> str | None:
    if not (
        isinstance(node, ast.Attribute)
        and node.attr == "default"
        and isinstance(node.value, ast.Subscript)
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == FUTURE_BY_KEY_SYMBOL
        and isinstance(node.value.slice, ast.Constant)
        and isinstance(node.value.slice.value, str)
    ):
        return None
    return node.value.slice.value


def test_current_moss_stream_budget_facade_declarations_are_exact() -> None:
    tree = _module_tree(config_module)
    assignments = _ttsconfig_assignments(tree)
    fields = dataclasses.fields(TTSConfig)
    field_names = tuple(field.name for field in fields)
    runtime_fields = {field.name: field for field in fields}
    hints = get_type_hints(TTSConfig)

    assert (len(fields), sum(field.init for field in fields)) == (179, 177)
    assert tuple(field.name for field in fields if not field.init) == (
        "_voices_cache",
        "_voices_cache_signature",
    )
    start = field_names.index(MOSS_STREAM_BUDGET_FIELDS[0])
    assert field_names[start : start + len(MOSS_STREAM_BUDGET_FIELDS)] == (
        MOSS_STREAM_BUDGET_FIELDS
    )
    assert field_names[start - 1] == "public_status_endpoints"
    assert field_names[start + len(MOSS_STREAM_BUDGET_FIELDS)] == (
        "model_idle_timeout_seconds"
    )
    assert tuple(
        name
        for name in field_names
        if name.startswith("moss_stream_budget_")
        or name == "moss_stream_chunk_min_floor"
    ) == MOSS_STREAM_BUDGET_FIELDS
    assert EXCLUDED_NEARBY_FIELDS.isdisjoint(MOSS_STREAM_BUDGET_FIELDS)

    for key, annotation, default in EXPECTED_FACADE:
        declaration = assignments[key]
        assert ast.unparse(declaration.annotation) == "float"
        assert hints[key] is annotation
        assert runtime_fields[key].default == default
        assert runtime_fields[key].init is True


def test_current_moss_stream_budget_runtime_reader_boundaries_are_exact() -> None:
    tree = _module_tree(moss_engine_streaming)
    decode = _definition(tree, "_resolve_stream_decode_frame_budget")
    split = _definition(tree, "_split_waveform_for_stream")

    decode_calls = _field_bound_getattr_calls(decode)
    split_calls = _field_bound_getattr_calls(split)
    assert tuple(decode_calls) == MOSS_STREAM_BUDGET_FIELDS[:3]
    assert tuple(split_calls) == MOSS_STREAM_BUDGET_FIELDS[3:]
    assert all(
        len(call.args) >= 3 and ast.unparse(call.args[0]) == "self.config"
        for call in (*decode_calls.values(), *split_calls.values())
    )

    decode_call_names = {
        item.func.id
        for item in ast.walk(decode)
        if isinstance(item, ast.Call) and isinstance(item.func, ast.Name)
    }
    split_call_names = {
        item.func.id
        for item in ast.walk(split)
        if isinstance(item, ast.Call) and isinstance(item.func, ast.Name)
    }
    assert {
        "StreamBudgetThresholds",
        "resolve_stream_decode_frame_budget",
    } <= decode_call_names
    assert "split_waveform_for_stream" in split_call_names


def test_current_moss_stream_budget_pure_helper_defaults_match_facade() -> None:
    threshold_defaults = tuple(
        field.default
        for field in dataclasses.fields(
            moss_runtime_streaming.StreamBudgetThresholds
        )
    )
    assert threshold_defaults == tuple(
        default for _key, _annotation, default in EXPECTED_FACADE[:3]
    )
    assert (
        moss_runtime_streaming.resolve_stream_decode_frame_budget.__module__
        == "kokoro_tts.moss_runtime.streaming"
    )
    assert (
        moss_runtime_audio.split_waveform_for_stream.__module__
        == "kokoro_tts.moss_runtime.audio"
    )

    for module in (moss_runtime_streaming, moss_runtime_audio):
        assert FUTURE_OWNER_MODULE.rsplit(".", 1)[-1] not in ast.unparse(
            _module_tree(module)
        )


def test_current_moss_stream_budget_env_owner_and_ranges_are_exact() -> None:
    actual = {
        env_name: (spec.attr, spec.min_value, spec.max_value)
        for env_name, spec in config_env.FLOAT_ENV.items()
        if spec.attr in MOSS_STREAM_BUDGET_FIELDS
    }
    assert actual == EXPECTED_ENV
    assert all(
        type(config_env.FLOAT_ENV[env_name]).__name__ == "FloatEnvSpec"
        for env_name in EXPECTED_ENV
    )
    assert not {
        spec.attr
        for mapping in (config_env.INT_ENV,)
        for spec in mapping.values()
    } & set(MOSS_STREAM_BUDGET_FIELDS)
    assert not {
        attr
        for mapping in (config_env.STR_ENV, config_env.BOOL_ENV)
        for attr in mapping.values()
    } & set(MOSS_STREAM_BUDGET_FIELDS)


def test_current_moss_stream_budget_worker_owner_and_admin_absence_are_exact(
) -> None:
    assert {
        env_name: attr
        for env_name, attr in server._WORKER_ENV_EXPORTS.items()
        if attr in MOSS_STREAM_BUDGET_FIELDS
    } == EXPECTED_WORKER_EXPORTS
    assert not set(MOSS_STREAM_BUDGET_FIELDS) & set(ADMIN_CONFIG_FIELDS)


def test_future_owner_module_gate_a() -> None:
    spec = importlib.util.find_spec(FUTURE_OWNER_MODULE)
    assert spec is not None, "MOSS Stream Budget owner module is missing"

    module = importlib.import_module(FUTURE_OWNER_MODULE)
    metadata = getattr(module, FUTURE_METADATA_SYMBOL)
    by_key = getattr(module, FUTURE_BY_KEY_SYMBOL)
    declaration_type = type(metadata[0])

    assert isinstance(metadata, tuple)
    assert len(metadata) == len(MOSS_STREAM_BUDGET_FIELDS)
    assert tuple((item.key, item.annotation, item.default) for item in metadata) == (
        EXPECTED_FACADE
    )
    assert declaration_type.__name__ == FUTURE_OWNER_TYPE
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
    assert all(not hasattr(item, "__dict__") for item in metadata)
    for item in metadata:
        with pytest.raises(
            (dataclasses.FrozenInstanceError, AttributeError, TypeError)
        ):
            item.default = object()

    assert isinstance(by_key, MappingProxyType)
    assert tuple(by_key) == MOSS_STREAM_BUDGET_FIELDS
    assert all(by_key[item.key] is item for item in metadata)
    with pytest.raises(TypeError):
        by_key[MOSS_STREAM_BUDGET_FIELDS[0]] = metadata[0]

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
        for token in (
            "admin",
            "audio",
            "config_env",
            "engine",
            "network",
            "process",
            "runtime",
            "server",
            "worker",
        )
    )
    assert not any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for node in owner_tree.body
    )
    assert [
        node.name for node in owner_tree.body if isinstance(node, ast.ClassDef)
    ] == [FUTURE_OWNER_TYPE]
    assignment_names: set[str] = set()
    for node in owner_tree.body:
        targets: list[ast.expr]
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        assignment_names.update(
            target.id for target in targets if isinstance(target, ast.Name)
        )
    assert assignment_names <= {
        FUTURE_METADATA_SYMBOL,
        FUTURE_BY_KEY_SYMBOL,
        "__all__",
    }


def test_future_ttsconfig_consumption_gate_b() -> None:
    tree = _module_tree(config_module)
    assignments = _ttsconfig_assignments(tree)
    direct_literals = tuple(
        field_name
        for field_name in MOSS_STREAM_BUDGET_FIELDS
        if isinstance(assignments[field_name].value, ast.Constant)
    )
    assert not direct_literals, "TTSConfig still declares direct literal defaults"

    canonical_imports = [
        node
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        and (node.module or "").endswith(
            "moss_stream_budget_config_metadata"
        )
        and any(
            alias.name == FUTURE_BY_KEY_SYMBOL and alias.asname is None
            for alias in node.names
        )
    ]
    assert len(canonical_imports) == 1, (
        "TTSConfig must explicitly import the canonical MOSS Stream Budget "
        "by-key owner"
    )

    assert {
        field_name: _canonical_owner_default_key(assignments[field_name].value)
        for field_name in MOSS_STREAM_BUDGET_FIELDS
    } == {field_name: field_name for field_name in MOSS_STREAM_BUDGET_FIELDS}

    local_owner_tables = {
        target.id
        for node in tree.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        for target in (
            node.targets
            if isinstance(node, ast.Assign)
            else [node.target]
        )
        if isinstance(target, ast.Name)
        and target.id.startswith("MOSS_STREAM_BUDGET_CONFIG_")
    }
    assert not local_owner_tables
