"""Freeze the P2-004 MOSS adapter fallback-ownership migration seam.

The two current-state tests preserve effective partial-config semantics without
freezing the adapter's third-argument syntax.  The two independent future gates
remain RED until the config-aware adapter imports and consumes the canonical
metadata owner.  Pure-helper defaults and layering remain owned by the P2-001
contract and are deliberately outside this file.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from kokoro_tts import moss_engine_streaming
from kokoro_tts.moss_engine_streaming import MossStreamingMixin
from kokoro_tts.moss_stream_budget_config_metadata import (
    MOSS_STREAM_BUDGET_CONFIG_BY_KEY,
)


pytestmark = pytest.mark.contract

TARGET_FIELDS = (
    "moss_stream_budget_threshold_low",
    "moss_stream_budget_threshold_mid",
    "moss_stream_budget_threshold_high",
    "moss_stream_chunk_min_floor",
)
CANONICAL_OWNER_MODULE = "moss_stream_budget_config_metadata"
CANONICAL_OWNER_SYMBOL = "MOSS_STREAM_BUDGET_CONFIG_BY_KEY"


def _module_tree(module) -> ast.Module:  # noqa: ANN001
    return ast.parse(Path(module.__file__).read_text(encoding="utf-8"))


def _definition(tree: ast.AST, name: str) -> ast.FunctionDef:
    return next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def _field_bound_getattr_calls(
    definition: ast.FunctionDef,
    expected_fields: tuple[str, ...],
) -> dict[str, ast.Call]:
    calls: dict[str, ast.Call] = {}
    for node in ast.walk(definition):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 3
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value in expected_fields
        ):
            continue
        field = str(node.args[1].value)
        assert field not in calls, f"duplicate runtime fallback for {field}"
        calls[field] = node
    return calls


def _canonical_owner_default_key(node: ast.AST) -> str | None:
    if not (
        isinstance(node, ast.Attribute)
        and node.attr == "default"
        and isinstance(node.value, ast.Subscript)
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == CANONICAL_OWNER_SYMBOL
        and isinstance(node.value.slice, ast.Constant)
        and isinstance(node.value.slice.value, str)
    ):
        return None
    return node.value.slice.value


def test_current_moss_decode_budget_partial_config_semantics_are_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = []
    sentinel = object()

    def capture_budget(
        emitted_samples_total,
        sample_rate,
        first_audio_emitted_at_perf,
        thresholds,
    ):
        captured.append(
            (
                emitted_samples_total,
                sample_rate,
                first_audio_emitted_at_perf,
                thresholds,
            )
        )
        return sentinel

    monkeypatch.setattr(
        moss_engine_streaming,
        "resolve_stream_decode_frame_budget",
        capture_budget,
    )
    subject = MossStreamingMixin()
    subject.config = SimpleNamespace()

    assert subject._resolve_stream_decode_frame_budget(12, 24000, 3.5) is sentinel
    defaults = captured[-1][3]
    assert (defaults.low, defaults.mid, defaults.high) == tuple(
        MOSS_STREAM_BUDGET_CONFIG_BY_KEY[field].default
        for field in TARGET_FIELDS[:3]
    )

    subject.config = SimpleNamespace(
        moss_stream_budget_threshold_low=0.31,
        moss_stream_budget_threshold_mid=0.72,
        moss_stream_budget_threshold_high=1.43,
    )
    assert subject._resolve_stream_decode_frame_budget(24, 48000, None) is sentinel
    configured = captured[-1][3]
    assert (configured.low, configured.mid, configured.high) == (
        0.31,
        0.72,
        1.43,
    )


def test_current_moss_chunk_floor_partial_config_semantics_are_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = []
    sentinel = object()

    def capture_split(waveform, *, sample_rate, chunk_seconds, min_floor):
        captured.append((waveform, sample_rate, chunk_seconds, min_floor))
        return sentinel

    monkeypatch.setattr(
        moss_engine_streaming,
        "split_waveform_for_stream",
        capture_split,
    )
    subject = MossStreamingMixin()
    subject.sample_rate = 24000
    subject.config = SimpleNamespace()

    waveform = object()
    assert (
        subject._split_waveform_for_stream(waveform, chunk_seconds=0.4)
        is sentinel
    )
    assert captured[-1][3] == MOSS_STREAM_BUDGET_CONFIG_BY_KEY[
        "moss_stream_chunk_min_floor"
    ].default

    subject.config = SimpleNamespace(moss_stream_chunk_min_floor=0.17)
    assert (
        subject._split_waveform_for_stream(waveform, chunk_seconds=0.4)
        is sentinel
    )
    assert captured[-1][3] == 0.17


def test_future_runtime_owner_import_gate_a() -> None:
    tree = _module_tree(moss_engine_streaming)
    canonical_imports = [
        node
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        and node.level == 1
        and node.module == CANONICAL_OWNER_MODULE
        and any(
            alias.name == CANONICAL_OWNER_SYMBOL and alias.asname is None
            for alias in node.names
        )
    ]
    assert len(canonical_imports) == 1, (
        "MOSS adapter must import the canonical stream-budget by-key owner "
        "directly and without an alias"
    )


def test_future_fallback_consumption_gate_b() -> None:
    tree = _module_tree(moss_engine_streaming)
    decode = _definition(tree, "_resolve_stream_decode_frame_budget")
    split = _definition(tree, "_split_waveform_for_stream")
    calls = {
        **_field_bound_getattr_calls(decode, TARGET_FIELDS[:3]),
        **_field_bound_getattr_calls(split, TARGET_FIELDS[3:]),
    }

    assert tuple(calls) == TARGET_FIELDS
    assert all(ast.unparse(call.args[0]) == "self.config" for call in calls.values())
    assert {
        field: _canonical_owner_default_key(calls[field].args[2])
        for field in TARGET_FIELDS
    } == {field: field for field in TARGET_FIELDS}, (
        "all four adapter fallback defaults must come from the matching "
        "canonical metadata-owner entry"
    )
