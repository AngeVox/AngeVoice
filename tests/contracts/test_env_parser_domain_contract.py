"""Contracts for the first declaration-backed CACHE integer parser seam."""

from __future__ import annotations

import ast
import dataclasses
import inspect
import logging
from pathlib import Path

import pytest

from kokoro_tts import config_env, config_env_domain
from kokoro_tts.config import TTSConfig
from kokoro_tts.config_env_domain import CACHE_INT_DECLARATIONS, EnvIntDeclaration


pytestmark = pytest.mark.contract


EXPECTED_CACHE_DECLARATIONS = (
    ("KOKORO_CACHE_MAX_ITEMS", "cache_max_items", 0, None),
    ("KOKORO_CACHE_MAX_BYTES", "cache_max_bytes", 0, None),
    (
        "KOKORO_CACHE_SKIP_TEXT_OVER_CHARS",
        "cache_skip_text_over_chars",
        0,
        None,
    ),
    (
        "KOKORO_CACHE_SKIP_AUDIO_OVER_BYTES",
        "cache_skip_audio_over_bytes",
        0,
        None,
    ),
)


@pytest.fixture(autouse=True)
def _clean_parser_environment(monkeypatch) -> None:
    monkeypatch.delenv("P2B_INT", raising=False)


def test_cache_integer_declarations_are_frozen_slot_backed_and_exact() -> None:
    assert dataclasses.is_dataclass(EnvIntDeclaration)
    assert EnvIntDeclaration.__dataclass_params__.frozen is True
    assert hasattr(EnvIntDeclaration, "__slots__")
    assert isinstance(CACHE_INT_DECLARATIONS, tuple)
    assert tuple(
        (item.env_name, item.attr, item.min_value, item.max_value)
        for item in CACHE_INT_DECLARATIONS
    ) == EXPECTED_CACHE_DECLARATIONS
    assert len({item.env_name for item in CACHE_INT_DECLARATIONS}) == 4
    with pytest.raises(dataclasses.FrozenInstanceError):
        CACHE_INT_DECLARATIONS[0].attr = "replacement"


def test_cache_declaration_attributes_are_ttsconfig_fields() -> None:
    config_fields = {field.name for field in dataclasses.fields(TTSConfig)}
    assert {item.attr for item in CACHE_INT_DECLARATIONS} <= config_fields


def test_domain_module_has_no_forbidden_runtime_dependencies() -> None:
    source_path = Path(config_env_domain.__file__)
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imports = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    assert not any(isinstance(node, ast.ImportFrom) and node.level for node in imports)
    assert {
        alias.name
        for node in imports
        if isinstance(node, ast.Import)
        for alias in node.names
    } == {"logging", "os"}
    assert {
        (node.module, tuple(alias.name for alias in node.names))
        for node in imports
        if isinstance(node, ast.ImportFrom) and node.module != "__future__"
    } == {
        ("collections.abc", ("Callable",)),
        ("dataclasses", ("dataclass",)),
    }
    imported_modules = {
        node.module
        for node in imports
        if isinstance(node, ast.ImportFrom) and node.module
    }
    imported_modules.update(
        alias.name for node in imports if isinstance(node, ast.Import) for alias in node.names
    )
    assert not any(
        token in module.lower()
        for module in imported_modules
        for token in ("kokoro_tts", "config", "admin", "model_sources", "loader", "route", "engine")
    )
    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "clamp" not in called_names
    assert not {"Path", "urlopen", "load_runtime_config"} & called_names


def test_parse_int_env_preserves_missing_and_integer_input_behavior(
    monkeypatch, caplog
) -> None:
    monkeypatch.delenv("P2B_INT", raising=False)
    with caplog.at_level(logging.WARNING):
        assert config_env_domain.parse_int_env("P2B_INT", 13) == 13
    assert caplog.records == []

    for raw, expected in (("7", 7), ("  7  ", 7), ("+7", 7), ("-7", -7)):
        monkeypatch.setenv("P2B_INT", raw)
        assert config_env_domain.parse_int_env("P2B_INT", 13) == expected


@pytest.mark.parametrize("raw", ("", "1.5"))
def test_parse_int_env_invalid_values_warn_once_and_return_default(
    monkeypatch, caplog, raw
) -> None:
    monkeypatch.setenv("P2B_INT", raw)
    with caplog.at_level(logging.WARNING, logger="kokoro_tts.config_env_domain"):
        assert config_env_domain.parse_int_env("P2B_INT", 13) == 13
    records = [record for record in caplog.records if record.name.endswith("config_env_domain")]
    assert len(records) == 1
    assert records[0].getMessage() == f"忽略无效整数环境变量 P2B_INT={raw!r}"


def test_legacy_wrapper_signature_and_delegation(monkeypatch) -> None:
    signature = inspect.signature(config_env.get_env_int)
    parameters = list(signature.parameters.values())
    assert config_env.get_env_int.__module__ == "kokoro_tts.config_env"
    assert [parameter.name for parameter in parameters] == ["name", "default"]
    assert all(
        parameter.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
        for parameter in parameters
    )
    assert not any(
        parameter.kind
        in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}
        for parameter in parameters
    )
    seen = {}

    def fake_parser(name, default, *, warning_sink):
        seen.update(name=name, default=default, logger_name=warning_sink.__self__.name)
        return 17

    monkeypatch.setattr(config_env, "parse_int_env", fake_parser)
    assert config_env.get_env_int("P2B_INT", 13) == 17
    assert seen == {
        "name": "P2B_INT",
        "default": 13,
        "logger_name": "kokoro_tts.config_env",
    }



def test_legacy_wrapper_invalid_value_keeps_config_env_logger(monkeypatch, caplog) -> None:
    monkeypatch.setenv("P2B_INT", "not-an-int")
    with caplog.at_level(logging.WARNING, logger="kokoro_tts.config_env"):
        assert config_env.get_env_int("P2B_INT", 13) == 13
    records = [record for record in caplog.records if record.name == "kokoro_tts.config_env"]
    assert len(records) == 1
    assert records[0].getMessage() == "忽略无效整数环境变量 P2B_INT='not-an-int'"


def test_parser_does_not_clamp_while_apply_env_keeps_clamp_owner(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("P2B_INT", "-7")
    assert config_env_domain.parse_int_env("P2B_INT", 13) == -7

    monkeypatch.setenv("KOKORO_CACHE_MAX_ITEMS", "-7")
    cfg = TTSConfig(model_dir=tmp_path / "model")
    config_env.apply_env(cfg)
    assert cfg.cache_max_items == 0
