"""Freeze the Rate Limit default/range ownership migration seam.

Current-state tests preserve the two-field facade, its local ENV/Admin
validation projections, and the independent middleware/profile policy.  The
two future gates remain independently red until both projection modules import
and consume the existing canonical metadata owner.
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path
from types import MappingProxyType

import pytest

from kokoro_tts import config_env, rate_limit_config_metadata
from kokoro_tts.admin_config import ADMIN_CONFIG_FIELDS, ADMIN_CONFIG_PROFILES
from kokoro_tts.config import TTSConfig
from kokoro_tts.rate_limit import TokenBucket


pytestmark = pytest.mark.contract


PACKAGE_ROOT = Path(__file__).parents[2] / "src" / "kokoro_tts"
CONFIG_ENV_PATH = PACKAGE_ROOT / "config_env.py"
ADMIN_SECURITY_PATH = (
    PACKAGE_ROOT / "admin_config" / "groups" / "security.py"
)
RATE_LIMIT_PATH = PACKAGE_ROOT / "rate_limit.py"

RATE_LIMIT_FIELDS = (
    "rate_limit_qps",
    "rate_limit_burst",
)
EXPECTED_DEFAULTS = {
    "rate_limit_qps": 10.0,
    "rate_limit_burst": 20,
}
EXPECTED_ENV = {
    "KOKORO_RATE_LIMIT_QPS": (
        "FLOAT_ENV",
        "FloatEnvSpec",
        "rate_limit_qps",
        0.0,
        None,
    ),
    "KOKORO_RATE_LIMIT_BURST": (
        "INT_ENV",
        "IntEnvSpec",
        "rate_limit_burst",
        0,
        None,
    ),
}
EXPECTED_ADMIN = {
    "rate_limit_qps": (10.0, 0, 1000, 0.1),
    "rate_limit_burst": (20, 0, 10000, 1),
}
CANONICAL_OWNER_MODULE = "rate_limit_config_metadata"
CANONICAL_OWNER_SYMBOL = "RATE_LIMIT_CONFIG_BY_KEY"


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _assignment_value(tree: ast.Module, name: str) -> ast.AST:
    matches: list[ast.AST] = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        ):
            matches.append(node.value)
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
            and node.value is not None
        ):
            matches.append(node.value)
    assert len(matches) == 1, f"expected one assignment for {name}"
    return matches[0]


def _env_spec_calls(tree: ast.Module) -> dict[str, ast.Call]:
    calls: dict[str, ast.Call] = {}
    for env_name, (mapping_name, constructor, *_rest) in EXPECTED_ENV.items():
        mapping = _assignment_value(tree, mapping_name)
        assert isinstance(mapping, ast.Dict)
        matches = [
            value
            for key, value in zip(mapping.keys, mapping.values, strict=True)
            if isinstance(key, ast.Constant) and key.value == env_name
        ]
        assert len(matches) == 1, f"expected one ENV row for {env_name}"
        call = matches[0]
        assert isinstance(call, ast.Call)
        assert isinstance(call.func, ast.Name) and call.func.id == constructor
        assert not call.keywords
        calls[env_name] = call
    return calls


def _admin_field_calls(tree: ast.Module) -> dict[str, ast.Call]:
    found: dict[str, list[ast.Call]] = {field: [] for field in RATE_LIMIT_FIELDS}
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "field_def"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value in found
        ):
            continue
        found[str(node.args[0].value)].append(node)
    assert all(len(calls) == 1 for calls in found.values())
    return {field: calls[0] for field, calls in found.items()}


def _owner_import_bindings(tree: ast.Module) -> set[str]:
    bindings: set[str] = set()
    for node in tree.body:
        if not (
            isinstance(node, ast.ImportFrom)
            and node.module == CANONICAL_OWNER_MODULE
        ):
            continue
        bindings.update(
            alias.asname or alias.name
            for alias in node.names
            if alias.name == CANONICAL_OWNER_SYMBOL
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
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.value is not None
        ):
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


def test_current_rate_limit_metadata_owner_and_defaults_are_exact() -> None:
    metadata = rate_limit_config_metadata.RATE_LIMIT_CONFIG_METADATA
    by_key = rate_limit_config_metadata.RATE_LIMIT_CONFIG_BY_KEY
    live_fields = tuple(
        field.name
        for field in dataclasses.fields(TTSConfig)
        if field.name.startswith("rate_limit_")
    )

    assert live_fields == RATE_LIMIT_FIELDS
    assert isinstance(metadata, tuple)
    assert tuple(item.key for item in metadata) == RATE_LIMIT_FIELDS
    assert isinstance(by_key, MappingProxyType)
    assert tuple(by_key) == RATE_LIMIT_FIELDS
    assert all(by_key[item.key] is item for item in metadata)

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
    assert {item.key: item.default for item in metadata} == EXPECTED_DEFAULTS
    assert {
        field: TTSConfig.__dataclass_fields__[field].default
        for field in RATE_LIMIT_FIELDS
    } == EXPECTED_DEFAULTS


def test_current_rate_limit_admin_and_env_validation_sources_are_exact() -> None:
    qps_spec = config_env.FLOAT_ENV["KOKORO_RATE_LIMIT_QPS"]
    burst_spec = config_env.INT_ENV["KOKORO_RATE_LIMIT_BURST"]
    assert (
        qps_spec.attr,
        qps_spec.min_value,
        qps_spec.max_value,
    ) == ("rate_limit_qps", 0.0, None)
    assert (
        burst_spec.attr,
        burst_spec.min_value,
        burst_spec.max_value,
    ) == ("rate_limit_burst", 0, None)

    assert {
        field: (
            ADMIN_CONFIG_FIELDS[field].default,
            ADMIN_CONFIG_FIELDS[field].min_value,
            ADMIN_CONFIG_FIELDS[field].max_value,
            ADMIN_CONFIG_FIELDS[field].step,
        )
        for field in RATE_LIMIT_FIELDS
    } == EXPECTED_ADMIN

def test_current_rate_limit_policy_and_sentinel_boundaries_are_preserved() -> None:
    assert {
        profile: tuple(
            ADMIN_CONFIG_PROFILES[profile]["values"][field]
            for field in RATE_LIMIT_FIELDS
        )
        for profile in ("deploy_lan_default", "deploy_public_hardened")
    } == {
        "deploy_lan_default": (10.0, 20),
        "deploy_public_hardened": (3.0, 6),
    }

    bucket = TokenBucket(qps=-1.0, burst=0)
    assert bucket.acquire() is True
    assert bucket.acquire() is False
    assert bucket.retry_after == 1.0
    assert not _owner_import_bindings(_tree(RATE_LIMIT_PATH))


def test_future_rate_limit_owner_import_gate_a() -> None:
    actual = {
        "config_env": _owner_import_bindings(_tree(CONFIG_ENV_PATH)),
        "admin_security": _owner_import_bindings(_tree(ADMIN_SECURITY_PATH)),
    }
    assert actual == {
        "config_env": {CANONICAL_OWNER_SYMBOL},
        "admin_security": {CANONICAL_OWNER_SYMBOL},
    }, (
        "Rate Limit ENV and Admin projection modules must import the canonical "
        "RATE_LIMIT_CONFIG_BY_KEY owner directly and without aliases"
    )


def test_future_rate_limit_admin_env_owner_consumption_gate_b() -> None:
    env_tree = _tree(CONFIG_ENV_PATH)
    env_bindings = _owner_import_bindings(env_tree)
    env_definitions = _top_level_definitions(env_tree)
    env_actual: dict[str, tuple[bool, bool, bool] | str] = {}
    for env_name, call in _env_spec_calls(env_tree).items():
        if len(call.args) != 3:
            env_actual[env_name] = f"positional_args={len(call.args)}"
            continue
        env_actual[env_name] = tuple(
            _depends_on_owner(
                arg,
                owner_bindings=env_bindings,
                definitions=env_definitions,
            )
            for arg in call.args
        )

    admin_tree = _tree(ADMIN_SECURITY_PATH)
    admin_bindings = _owner_import_bindings(admin_tree)
    admin_definitions = _top_level_definitions(admin_tree)
    admin_actual = {
        field: tuple(
            _depends_on_owner(
                arg,
                owner_bindings=admin_bindings,
                definitions=admin_definitions,
            )
            for arg in call.args[5:9]
        )
        for field, call in _admin_field_calls(admin_tree).items()
    }

    assert {
        "env_attr_min_max": env_actual,
        "admin_default_min_max_step": admin_actual,
    } == {
        "env_attr_min_max": {
            env_name: (True, True, True) for env_name in EXPECTED_ENV
        },
        "admin_default_min_max_step": {
            field: (True, True, True, True) for field in RATE_LIMIT_FIELDS
        },
    }, (
        "each Rate Limit ENV attr/min/max argument and Admin "
        "default/min/max/step argument must consume the canonical owner"
    )
