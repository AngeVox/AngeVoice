"""Freeze UpdateChecker fallback ownership without removing duck typing.

The current-state tests are permanent behavior and layering contracts.  The
two future-state gates remain independently red until UpdateChecker derives
its four fallback values from the existing canonical metadata owner.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from kokoro_tts import update_check_config_metadata
from kokoro_tts.update_checker import UpdateChecker


pytestmark = pytest.mark.contract

TARGET_FIELDS = (
    "update_check_enabled",
    "update_repository",
    "update_check_timeout_seconds",
    "update_check_cache_seconds",
)

# TEST_EXPECTATION_ONLY: production truth remains UPDATE_CHECK_CONFIG_BY_KEY.
EXPECTED_DEFAULTS = {
    "update_check_enabled": True,
    "update_repository": "angevox/AngeVoice",
    "update_check_timeout_seconds": 3.0,
    "update_check_cache_seconds": 21600.0,
}

EXPECTED_GETATTR_BOUNDARIES = {
    ("__init__", "update_check_enabled"): "cfg",
    ("__init__", "update_repository"): "cfg",
    ("__init__", "update_check_cache_seconds"): "cfg",
    ("check", "update_check_timeout_seconds"): "self.cfg",
}

CANONICAL_OWNER_SYMBOL = "UPDATE_CHECK_CONFIG_BY_KEY"


def _source_tree(module) -> ast.Module:  # noqa: ANN001
    return ast.parse(Path(module.__file__).read_text(encoding="utf-8"))


def _update_checker_tree() -> ast.Module:
    import kokoro_tts.update_checker as update_checker_module

    return _source_tree(update_checker_module)


def _target_getattr_calls() -> dict[tuple[str, str], ast.Call]:
    tree = _update_checker_tree()
    checker = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "UpdateChecker"
    )
    found: dict[tuple[str, str], list[ast.Call]] = {}
    for method in checker.body:
        if not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(method):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "getattr"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value in TARGET_FIELDS
            ):
                continue
            field = str(node.args[1].value)
            found.setdefault((method.name, field), []).append(node)

    assert set(found) == set(EXPECTED_GETATTR_BOUNDARIES)
    assert all(len(calls) == 1 for calls in found.values())
    return {key: calls[0] for key, calls in found.items()}


def _imported_modules(tree: ast.Module) -> set[str]:
    modules: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            modules.add("." * node.level + (node.module or ""))
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return modules


def _canonical_default_key(node: ast.AST) -> str | None:
    if not (
        isinstance(node, ast.Attribute)
        and node.attr == "default"
        and isinstance(node.value, ast.Subscript)
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == CANONICAL_OWNER_SYMBOL
    ):
        return None
    slice_node = node.value.slice
    if isinstance(slice_node, ast.Constant) and isinstance(slice_node.value, str):
        return slice_node.value
    return None


class _Response:
    def read(self) -> bytes:
        return b'{"tag_name":"v999.0.0","name":"Future release"}'


def test_current_update_check_partial_config_semantics_are_preserved() -> None:
    calls: list[float] = []

    def opener(_request, *, timeout):  # noqa: ANN001, ANN202
        calls.append(timeout)
        return _Response()

    disabled = UpdateChecker(
        SimpleNamespace(
            update_check_enabled=False,
            update_repository="disabled/repository",
            update_check_timeout_seconds=0.5,
            update_check_cache_seconds=12.0,
        ),
        opener=opener,
    )
    disabled_result = disabled.check(force=True)
    assert disabled_result["enabled"] is False
    assert disabled_result["repository"] == "disabled/repository"
    assert disabled._cache_seconds == 12.0
    assert calls == []

    configured = UpdateChecker(
        SimpleNamespace(
            update_check_enabled=True,
            update_repository="custom/repository",
            update_check_timeout_seconds=0.75,
            update_check_cache_seconds=42.0,
        ),
        opener=opener,
    )
    configured_result = configured.check(force=True)
    assert configured_result["repository"] == "custom/repository"
    assert configured._cache_seconds == 42.0
    assert calls.pop() == 0.75

    fallback = UpdateChecker(SimpleNamespace(), opener=opener)
    fallback_result = fallback.check(force=True)
    assert fallback_result["enabled"] is True
    assert fallback_result["repository"] == "angevox/AngeVoice"
    assert fallback._cache_seconds == 21600.0
    assert calls.pop() == 3.0
    assert calls == []


def test_current_update_check_runtime_reads_keep_getattr_compatibility_boundary(
) -> None:
    calls = _target_getattr_calls()
    for key, expected_receiver in EXPECTED_GETATTR_BOUNDARIES.items():
        call = calls[key]
        assert len(call.args) >= 3
        assert ast.unparse(call.args[0]) == expected_receiver

    checker = next(
        node
        for node in _update_checker_tree().body
        if isinstance(node, ast.ClassDef) and node.name == "UpdateChecker"
    )
    assert not {
        node.attr
        for node in ast.walk(checker)
        if isinstance(node, ast.Attribute) and node.attr in TARGET_FIELDS
    }


def test_current_update_check_canonical_metadata_defaults_are_exact() -> None:
    by_key = update_check_config_metadata.UPDATE_CHECK_CONFIG_BY_KEY
    assert tuple(by_key) == TARGET_FIELDS
    assert {field: by_key[field].default for field in TARGET_FIELDS} == (
        EXPECTED_DEFAULTS
    )

    seen_timeouts: list[float] = []

    def opener(_request, *, timeout):  # noqa: ANN001, ANN202
        seen_timeouts.append(timeout)
        return _Response()

    checker = UpdateChecker(SimpleNamespace(), opener=opener)
    result = checker.check(force=True)
    effective = {
        "update_check_enabled": result["enabled"],
        "update_repository": result["repository"],
        "update_check_timeout_seconds": seen_timeouts.pop(),
        "update_check_cache_seconds": checker._cache_seconds,
    }
    assert effective == {field: by_key[field].default for field in TARGET_FIELDS}


def test_current_update_check_layering_boundary_remains_narrow() -> None:
    owner_imports = {
        module.lstrip(".")
        for module in _imported_modules(_source_tree(update_check_config_metadata))
    }
    forbidden_owner_imports = {
        "admin_config",
        "config",
        "routes",
        "server",
        "update_checker",
    }
    assert not owner_imports & forbidden_owner_imports

    checker_tree = _update_checker_tree()
    checker_imports = {
        module.lstrip(".") for module in _imported_modules(checker_tree)
    }
    assert "config" not in checker_imports
    assert not any(
        alias.name == "TTSConfig"
        for node in checker_tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    )


def test_future_runtime_owner_import_gate_a() -> None:
    tree = _update_checker_tree()
    canonical_imports = [
        node
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        and node.level == 1
        and node.module == "update_check_config_metadata"
        and any(
            alias.name == CANONICAL_OWNER_SYMBOL and alias.asname is None
            for alias in node.names
        )
    ]
    assert len(canonical_imports) == 1, (
        "UpdateChecker must import UPDATE_CHECK_CONFIG_BY_KEY "
        "from update_check_config_metadata"
    )


def test_future_fallback_consumption_gate_b() -> None:
    calls = _target_getattr_calls()
    actual = {
        field: _canonical_default_key(calls[(method, field)].args[2])
        for method, field in EXPECTED_GETATTR_BOUNDARIES
    }
    expected = {field: field for field in TARGET_FIELDS}
    assert actual == expected, (
        "UpdateChecker fallback defaults still duplicate literals instead "
        "of consuming UPDATE_CHECK_CONFIG_BY_KEY"
    )
