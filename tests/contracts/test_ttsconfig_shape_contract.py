"""Characterization contract for the public TTSConfig 2.6.7 shape."""

from __future__ import annotations

import ast
import dataclasses
import inspect
import json
import re
from pathlib import Path
from typing import Any

import pytest

from kokoro_tts import config as config_module
from kokoro_tts.config import TTSConfig
from kokoro_tts.config_ids import MODEL_FILENAME


pytestmark = pytest.mark.contract

DATA_PATH = Path(__file__).parent / "data" / "ttsconfig_shape_2_6_7.json"
SNAPSHOT = json.loads(DATA_PATH.read_text(encoding="utf-8"))


def _normalize(value: Any, *, model_dir: Path) -> Any:
    if isinstance(value, Path):
        if value == model_dir:
            return "<MODEL_DIR_OVERRIDE>"
        return value.as_posix()
    if isinstance(value, tuple):
        return [_normalize(item, model_dir=model_dir) for item in value]
    if isinstance(value, list):
        return [_normalize(item, model_dir=model_dir) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _normalize(item, model_dir=model_dir)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise TypeError(f"unsupported contract value: {type(value)!r}")


def _qualified_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_qualified_name(node.value)}.{node.attr}"
    raise TypeError(ast.dump(node))


def _canonical_annotation(node: ast.AST) -> str:
    if isinstance(node, (ast.Name, ast.Attribute)):
        return _qualified_name(node)
    if isinstance(node, ast.Constant) and node.value is None:
        return "None"
    if isinstance(node, ast.Constant) and node.value is Ellipsis:
        return "..."
    if isinstance(node, ast.Subscript):
        return f"{_canonical_annotation(node.value)}[{_canonical_annotation(node.slice)}]"
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return f"{_canonical_annotation(node.left)}|{_canonical_annotation(node.right)}"
    if isinstance(node, (ast.Tuple, ast.List)):
        return ",".join(_canonical_annotation(item) for item in node.elts)
    raise TypeError(f"unsupported annotation: {ast.dump(node)}")


def _source_annotations() -> dict[str, str]:
    source = Path(config_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    tts_config = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "TTSConfig"
    )
    return {
        node.target.id: _canonical_annotation(node.annotation)
        for node in tts_config.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }


def _factory_contract(factory) -> dict[str, str]:
    if factory.__name__ == "<lambda>":
        return {"kind": "lambda", "name": "<lambda>"}
    return {"kind": "named_function", "name": factory.__name__}


def _runtime_shape(model_dir: Path) -> dict[str, Any]:
    cfg = TTSConfig(model_dir=model_dir)
    annotations = _source_annotations()
    fields = []
    factories = []
    for field in dataclasses.fields(TTSConfig):
        if field.default_factory is not dataclasses.MISSING:
            descriptor = _factory_contract(field.default_factory)
            factories.append({"field": field.name, **descriptor})
            default_kind = "factory"
            default = (
                {"evaluated": False, "factory": descriptor}
                if field.name == "model_dir"
                else _normalize(getattr(cfg, field.name), model_dir=model_dir)
            )
        elif field.default is not dataclasses.MISSING:
            default_kind = "value"
            default = _normalize(field.default, model_dir=model_dir)
        else:
            default_kind = "missing"
            default = None
        fields.append(
            {
                "name": field.name,
                "annotation": annotations[field.name],
                "init": field.init,
                "repr": field.repr,
                "compare": field.compare,
                "kw_only": field.kw_only,
                "default_kind": default_kind,
                "default": default,
            }
        )
    properties = [
        name for name, value in TTSConfig.__dict__.items() if isinstance(value, property)
    ]
    return {
        "contract": "AngeVoice TTSConfig 2.6.7 public shape",
        "field_count": len(fields),
        "fields": fields,
        "constructor_parameters": list(inspect.signature(TTSConfig).parameters),
        "default_factory_fields": factories,
        "model_dir_factory": _factory_contract(
            next(
                field
                for field in dataclasses.fields(TTSConfig)
                if field.name == "model_dir"
            ).default_factory
        ),
        "properties": properties,
        "compatibility_methods": ["get_voices"],
    }


def test_ttsconfig_shape_matches_checked_in_2_6_7_snapshot(tmp_path) -> None:
    assert _runtime_shape(tmp_path / "model") == SNAPSHOT
    assert SNAPSHOT["field_count"] == 179
    assert SNAPSHOT["model_dir_factory"] == {
        "kind": "named_function",
        "name": "_find_models_dir",
    }
    cache_fields = {
        field["name"]: field
        for field in SNAPSHOT["fields"]
        if field["name"] in {"_voices_cache", "_voices_cache_signature"}
    }
    assert set(cache_fields) == {"_voices_cache", "_voices_cache_signature"}
    assert all(field["init"] is False for field in cache_fields.values())


def test_constructor_order_is_exactly_the_init_field_order() -> None:
    init_fields = [field["name"] for field in SNAPSHOT["fields"] if field["init"]]
    assert SNAPSHOT["constructor_parameters"] == init_fields
    assert "_voices_cache" not in inspect.signature(TTSConfig).parameters
    assert "_voices_cache_signature" not in inspect.signature(TTSConfig).parameters
    public_init_fields = {
        field["name"]
        for field in SNAPSHOT["fields"]
        if field["init"] and not field["name"].startswith("_")
    }
    assert public_init_fields <= set(inspect.signature(TTSConfig).parameters)


@pytest.mark.parametrize(
    "overrides",
    [
        {
            "device": "cpu",
            "port": 9001,
            "cache_enabled": False,
            "cors_origins": ["https://contract.invalid"],
        },
        {
            "moss_cpu_threads": 2,
            "moss_model_dir": Path("contract-moss"),
            "model_source": "offline",
        },
        {
            "zipvoice_num_steps": 7,
            "zipvoice_repo_path": Path("contract-zipvoice"),
            "request_timeout_seconds": 1.5,
        },
    ],
)
def test_representative_public_fields_remain_keyword_constructible(
    tmp_path, overrides
) -> None:
    cfg = TTSConfig(model_dir=tmp_path, **overrides)
    for name, expected in overrides.items():
        assert getattr(cfg, name) == expected


def test_properties_are_read_only_and_keep_path_semantics(tmp_path) -> None:
    cfg = TTSConfig(model_dir=tmp_path)
    assert cfg.model_path == str(tmp_path)
    assert cfg.model_file == tmp_path / MODEL_FILENAME
    assert cfg.voices_dir == tmp_path / "voices"
    for name in ("model_path", "model_file", "voices_dir"):
        descriptor = inspect.getattr_static(TTSConfig, name)
        assert isinstance(descriptor, property)
        assert descriptor.fset is None
        with pytest.raises(AttributeError):
            setattr(cfg, name, "replacement")


def test_get_voices_returns_sorted_copies_from_the_current_model_dir(
    monkeypatch, tmp_path
) -> None:
    voices = tmp_path / "voices"
    voices.mkdir()
    (voices / "b.pt").write_bytes(b"contract")
    (voices / "a.pt").write_bytes(b"contract")
    monkeypatch.setattr(config_module, "is_valid_kokoro_voice_file", lambda *_a, **_k: True)
    cfg = TTSConfig(model_dir=tmp_path)
    first = cfg.get_voices()
    assert first == ["a", "b"]
    first.append("mutated-by-caller")
    assert cfg.get_voices() == ["a", "b"]


def test_snapshots_are_static_expectations_and_contain_no_machine_paths() -> None:
    assert DATA_PATH.is_file()
    serialized = DATA_PATH.read_text(encoding="utf-8")
    assert not re.search(r'(?m)"[A-Za-z]:[\\/]', serialized)
    forbidden_tokens = [
        "snapshot" + "-generator",
        "json." + "dump(",
        "." + "write_text(",
    ]
    for test_path in Path(__file__).parent.glob("test_*_contract.py"):
        source = test_path.read_text(encoding="utf-8")
        assert all(token not in source for token in forbidden_tokens)
