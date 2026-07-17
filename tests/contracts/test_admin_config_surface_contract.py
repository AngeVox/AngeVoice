"""Characterization contract for the Admin config 2.6.7 surface."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from kokoro_tts import admin_config as package_facade
from kokoro_tts import admin_config_schema as legacy_facade
from kokoro_tts import config_env
from kokoro_tts.config import TTSConfig


pytestmark = pytest.mark.contract

DATA_PATH = Path(__file__).parent / "data" / "admin_config_surface_2_6_7.json"
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
    raise TypeError(f"unsupported Admin contract value: {type(value)!r}")


def _runtime_schema(model_dir: Path) -> dict[str, Any]:
    payload = _normalize(package_facade.schema_payload(), model_dir=model_dir)
    return {
        "groups": payload["groups"],
        "fields": payload["fields"],
        "profile_keys": [profile["key"] for profile in payload["profiles"]],
    }


def _runtime_comparisons(model_dir: Path) -> list[dict[str, Any]]:
    cfg = TTSConfig(model_dir=model_dir)
    schema = _runtime_schema(model_dir)
    int_by_attr: dict[str, list[dict[str, Any]]] = {}
    for env, spec in config_env.INT_ENV.items():
        int_by_attr.setdefault(spec.attr, []).append(
            {"env": env, "min": spec.min_value, "max": spec.max_value}
        )
    float_by_attr: dict[str, list[dict[str, Any]]] = {}
    for env, spec in config_env.FLOAT_ENV.items():
        float_by_attr.setdefault(spec.attr, []).append(
            {"env": env, "min": spec.min_value, "max": spec.max_value}
        )
    comparisons = []
    for field in schema["fields"]:
        key = field["key"]
        env_ranges = sorted(
            int_by_attr.get(key, []) + float_by_attr.get(key, []),
            key=lambda item: item["env"],
        )
        admin_range = {"min": field["min"], "max": field["max"]}
        comparisons.append(
            {
                "key": key,
                "config_default": _normalize(getattr(cfg, key), model_dir=model_dir),
                "admin_default": field["default"],
                "default_equal": _normalize(
                    getattr(cfg, key), model_dir=model_dir
                )
                == field["default"],
                "env_ranges": env_ranges,
                "admin_range": admin_range,
                "range_equal": (
                    all(
                        {"min": item["min"], "max": item["max"]} == admin_range
                        for item in env_ranges
                    )
                    if env_ranges
                    else None
                ),
                "runtime_config_key": key,
            }
        )
    return comparisons


def test_schema_payload_matches_checked_in_81_field_snapshot(tmp_path) -> None:
    assert _runtime_schema(tmp_path / "model") == SNAPSHOT["schema"]
    assert SNAPSHOT["field_count"] == 81
    assert SNAPSHOT["group_order"] == [
        group["key"] for group in SNAPSHOT["schema"]["groups"]
    ]
    assert SNAPSHOT["field_order"] == [
        field["key"] for field in SNAPSHOT["schema"]["fields"]
    ]


def test_all_admin_keys_are_ttsconfig_fields_and_runtime_keys_are_unchanged(
    tmp_path,
) -> None:
    config_fields = {field.name for field in dataclasses.fields(TTSConfig)}
    assert set(SNAPSHOT["field_order"]) <= config_fields
    values = {
        field["key"]: field["default"] for field in SNAPSHOT["schema"]["fields"]
    }
    cfg = TTSConfig(
        model_dir=tmp_path / "model",
        runtime_config_file=tmp_path / "runtime-config.json",
    )
    package_facade.save_runtime_config_values(cfg, values)
    persisted = package_facade.read_runtime_config_values(cfg.runtime_config_file)
    assert list(persisted) == SNAPSHOT["field_order"]
    assert set(persisted) == set(SNAPSHOT["field_order"])


def test_legacy_admin_config_schema_facade_matches_package_exports() -> None:
    assert legacy_facade.ADMIN_CONFIG_FIELDS is package_facade.ADMIN_CONFIG_FIELDS
    assert legacy_facade.ADMIN_CONFIG_GROUPS is package_facade.ADMIN_CONFIG_GROUPS
    assert legacy_facade.ADMIN_CONFIG_PROFILES is package_facade.ADMIN_CONFIG_PROFILES
    assert legacy_facade.schema_payload() == package_facade.schema_payload()
    assert (
        legacy_facade.validate_admin_config_values
        is package_facade.validate_admin_config_values
    )
    assert (
        legacy_facade.save_runtime_config_values
        is package_facade.save_runtime_config_values
    )


def test_known_default_and_range_divergences_are_frozen_not_repaired(
    tmp_path,
) -> None:
    current = _runtime_comparisons(tmp_path / "model")
    assert current == SNAPSHOT["comparisons"]
    default_divergences = [
        item for item in current if item["default_equal"] is False
    ]
    range_divergences = [
        item for item in current if item["range_equal"] is False
    ]
    assert len(default_divergences) == 1
    assert len(range_divergences) == 26
    assert all(
        item["runtime_config_key"] == item["key"] for item in current
    )
