"""P2-002 contract freeze for MOSS Stream Budget ENV declarations.

The permanent characterization protects the current effective ENV and worker
surfaces.  The four future gates independently define the narrow declaration
owner, metadata linkage, parser projection, and worker projection seams.
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path
from types import MappingProxyType

import pytest

from kokoro_tts import (
    config_env,
    config_env_domain,
    moss_stream_budget_config_metadata,
    server,
)


pytestmark = pytest.mark.contract

MOSS_STREAM_BUDGET_FIELDS = (
    "moss_stream_budget_threshold_low",
    "moss_stream_budget_threshold_mid",
    "moss_stream_budget_threshold_high",
    "moss_stream_chunk_min_floor",
)

EXPECTED_ENV = (
    (
        "MOSS_STREAM_BUDGET_THRESHOLD_LOW",
        "moss_stream_budget_threshold_low",
        0.0,
        None,
    ),
    (
        "MOSS_STREAM_BUDGET_THRESHOLD_MID",
        "moss_stream_budget_threshold_mid",
        0.0,
        None,
    ),
    (
        "MOSS_STREAM_BUDGET_THRESHOLD_HIGH",
        "moss_stream_budget_threshold_high",
        0.0,
        None,
    ),
    (
        "MOSS_STREAM_CHUNK_MIN_FLOOR",
        "moss_stream_chunk_min_floor",
        0.01,
        None,
    ),
)

DECLARATION_TYPE = "EnvFloatDeclaration"
DECLARATIONS_SYMBOL = "MOSS_STREAM_BUDGET_ENV_DECLARATIONS"
OPTIONAL_ENV_BY_KEY = "_MOSS_STREAM_BUDGET_ENV_BY_KEY"
EXPECTED_FUTURE_PRODUCTION_FILES = frozenset(
    {
        "src/kokoro_tts/config_env_domain.py",
        "src/kokoro_tts/moss_stream_budget_config_metadata.py",
        "src/kokoro_tts/config_env.py",
        "src/kokoro_tts/server.py",
    }
)


def _module_tree(module) -> ast.Module:  # noqa: ANN001
    return ast.parse(Path(module.__file__).read_text(encoding="utf-8"))


def _assignment_value(tree: ast.Module, name: str) -> ast.expr:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        ):
            return node.value
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
        ):
            return node.value
    raise AssertionError(f"missing module assignment: {name}")


def _imports_symbol(tree: ast.Module, module_leaf: str, symbol: str) -> bool:
    return any(
        isinstance(node, ast.ImportFrom)
        and (node.module or "").split(".")[-1] == module_leaf
        and any(alias.name == symbol for alias in node.names)
        for node in tree.body
    )


def _literal_dict_keys(value: ast.expr) -> set[str]:
    return {
        str(key.value)
        for node in ast.walk(value)
        if isinstance(node, ast.Dict)
        for key in node.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }


def _declaration_projection(value: ast.expr) -> ast.DictComp:
    projections = [
        node
        for node in ast.walk(value)
        if isinstance(node, ast.DictComp)
        and any(
            isinstance(item, ast.Name) and item.id == DECLARATIONS_SYMBOL
            for item in ast.walk(node)
        )
    ]
    assert len(projections) == 1, (
        f"expected one projection from {DECLARATIONS_SYMBOL}, "
        f"found {len(projections)}"
    )
    return projections[0]


def test_current_moss_stream_budget_env_effective_surface_is_preserved() -> None:
    actual_float = tuple(
        (
            env_name,
            config_env.FLOAT_ENV[env_name].attr,
            config_env.FLOAT_ENV[env_name].min_value,
            config_env.FLOAT_ENV[env_name].max_value,
        )
        for env_name, _attr, _minimum, _maximum in EXPECTED_ENV
    )
    assert actual_float == EXPECTED_ENV
    assert all(
        type(config_env.FLOAT_ENV[env_name]) is config_env.FloatEnvSpec
        for env_name, _attr, _minimum, _maximum in EXPECTED_ENV
    )
    assert tuple(
        env_name
        for env_name, spec in config_env.FLOAT_ENV.items()
        if spec.attr in MOSS_STREAM_BUDGET_FIELDS
    ) == tuple(row[0] for row in EXPECTED_ENV)

    expected_worker = {env_name: attr for env_name, attr, _min, _max in EXPECTED_ENV}
    actual_worker = {
        env_name: attr
        for env_name, attr in server._WORKER_ENV_EXPORTS.items()
        if attr in MOSS_STREAM_BUDGET_FIELDS
    }
    assert actual_worker == expected_worker
    assert len(actual_worker) == len(MOSS_STREAM_BUDGET_FIELDS)
    assert len(EXPECTED_FUTURE_PRODUCTION_FILES) == 4


def test_future_gate_a_declares_exact_immutable_float_env_owner() -> None:
    declaration_type = getattr(config_env_domain, DECLARATION_TYPE, None)
    assert declaration_type is not None, (
        f"Gate A: config_env_domain.{DECLARATION_TYPE} is missing"
    )
    assert dataclasses.is_dataclass(declaration_type)
    assert declaration_type.__dataclass_params__.frozen is True
    assert tuple(field.name for field in dataclasses.fields(declaration_type)) == (
        "env_name",
        "attr",
        "min_value",
        "max_value",
    )
    assert tuple(getattr(declaration_type, "__slots__", ())) == (
        "env_name",
        "attr",
        "min_value",
        "max_value",
    )

    domain_tree = _module_tree(config_env_domain)
    declaration_class = next(
        (
            node
            for node in domain_tree.body
            if isinstance(node, ast.ClassDef) and node.name == DECLARATION_TYPE
        ),
        None,
    )
    assert declaration_class is not None
    assert not any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for node in declaration_class.body
    )

    declarations = getattr(config_env_domain, DECLARATIONS_SYMBOL, None)
    assert declarations is not None, (
        f"Gate A: config_env_domain.{DECLARATIONS_SYMBOL} is missing"
    )
    assert isinstance(declarations, tuple)
    assert tuple(
        (item.env_name, item.attr, item.min_value, item.max_value)
        for item in declarations
    ) == EXPECTED_ENV
    assert all(type(item) is declaration_type for item in declarations)
    assert all(not hasattr(item, "__dict__") for item in declarations)
    with pytest.raises(
        (dataclasses.FrozenInstanceError, AttributeError, TypeError)
    ):
        declarations[0].attr = "mutated"


def test_future_gate_b_links_metadata_to_exact_env_declaration_identity() -> None:
    metadata_type = moss_stream_budget_config_metadata.MossStreamBudgetConfigMetadata
    fields = tuple(field.name for field in dataclasses.fields(metadata_type))
    assert fields == (
        "key",
        "annotation",
        "default",
        "env_declaration",
    ), "Gate B: metadata is not linked to an env_declaration field"

    declarations = getattr(config_env_domain, DECLARATIONS_SYMBOL, None)
    assert declarations is not None, "Gate B: ENV declaration identity target is missing"
    by_attr = {declaration.attr: declaration for declaration in declarations}
    metadata = moss_stream_budget_config_metadata.MOSS_STREAM_BUDGET_CONFIG_METADATA
    assert tuple(item.key for item in metadata) == MOSS_STREAM_BUDGET_FIELDS
    assert all(item.env_declaration is by_attr[item.key] for item in metadata)

    optional_index = getattr(
        moss_stream_budget_config_metadata,
        OPTIONAL_ENV_BY_KEY,
        None,
    )
    if optional_index is not None:
        assert isinstance(optional_index, MappingProxyType)
        assert tuple(optional_index) == MOSS_STREAM_BUDGET_FIELDS
        assert all(optional_index[key] is by_attr[key] for key in optional_index)


def test_future_gate_c_projects_config_env_from_shared_declarations() -> None:
    tree = _module_tree(config_env)
    assert _imports_symbol(tree, "config_env_domain", DECLARATIONS_SYMBOL), (
        f"Gate C: config_env does not import {DECLARATIONS_SYMBOL}"
    )
    float_env = _assignment_value(tree, "FLOAT_ENV")
    target_env_names = {row[0] for row in EXPECTED_ENV}
    assert target_env_names.isdisjoint(_literal_dict_keys(float_env)), (
        "Gate C: config_env still owns literal MOSS Stream Budget rows"
    )

    projection = _declaration_projection(float_env)
    assert ast.unparse(projection.key) == "declaration.env_name"
    assert isinstance(projection.value, ast.Call)
    assert isinstance(projection.value.func, ast.Name)
    assert projection.value.func.id == "FloatEnvSpec"
    assert tuple(ast.unparse(argument) for argument in projection.value.args) == (
        "declaration.attr",
        "declaration.min_value",
        "declaration.max_value",
    )


def test_future_gate_d_projects_worker_exports_from_shared_declarations() -> None:
    tree = _module_tree(server)
    assert _imports_symbol(tree, "config_env_domain", DECLARATIONS_SYMBOL), (
        f"Gate D: server does not import {DECLARATIONS_SYMBOL}"
    )
    worker_exports = _assignment_value(tree, "_WORKER_ENV_EXPORTS")
    target_env_names = {row[0] for row in EXPECTED_ENV}
    assert target_env_names.isdisjoint(_literal_dict_keys(worker_exports)), (
        "Gate D: server still owns literal MOSS Stream Budget worker rows"
    )

    projection = _declaration_projection(worker_exports)
    assert ast.unparse(projection.key) == "declaration.env_name"
    assert ast.unparse(projection.value) == "declaration.attr"
