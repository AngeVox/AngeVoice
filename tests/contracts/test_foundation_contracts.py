"""Cross-module behavior contracts required before structural refactoring."""

from __future__ import annotations

import json

import pytest

from kokoro_tts.config import TTSConfig, load_config
from kokoro_tts.engine_manager import EngineManager
from kokoro_tts.engines.registry import EngineRegistry


pytestmark = pytest.mark.contract


class _LifecycleEngine:
    def __init__(self, model_id: str):
        self.model_id = model_id
        self.is_loaded = False
        self.is_healthy = True
        self.load_count = 0
        self.unload_count = 0

    def load(self):
        self.is_loaded = True
        self.load_count += 1
        return self

    def unload(self, *args, **kwargs):
        self.is_loaded = False
        self.unload_count += 1

    def metadata(self):
        return {
            "id": self.model_id,
            "name": self.model_id,
            "backend": f"fake-{self.model_id}",
            "loaded": self.is_loaded,
        }


def test_engine_manager_load_switch_unload_and_status_contract(monkeypatch) -> None:
    cfg = TTSConfig(
        enabled_models=["kokoro", "moss", "zipvoice"],
        default_model="kokoro",
        model_unload_on_switch=True,
        model_idle_timeout_seconds=0,
    )
    manager = EngineManager(cfg)
    created: dict[str, _LifecycleEngine] = {}

    def create(model_id: str, *, provider_hint=None):
        engine = _LifecycleEngine(model_id)
        created[model_id] = engine
        return engine

    monkeypatch.setattr(manager, "_create_engine", create)
    try:
        kokoro = manager.get_engine("kokoro", load=True)
        assert kokoro.is_loaded is True
        assert kokoro.load_count == 1
        assert manager.current_snapshot()["id"] == "kokoro"

        switched = manager.switch_model("moss", unload_previous=True, load=True)
        assert switched["previous_model"] == "kokoro"
        assert switched["current_model"] == "moss"
        assert switched["unloaded_previous"] is True
        assert created["kokoro"].is_loaded is False
        assert created["moss"].is_loaded is True
        assert manager.current_snapshot()["id"] == "moss"

        assert manager.unload_model("moss") is True
        assert created["moss"].is_loaded is False
        assert manager.current_snapshot()["loaded"] is False
    finally:
        manager.stop_idle_timer()


def test_configuration_precedence_default_env_runtime_then_call(monkeypatch, tmp_path) -> None:
    """Public configuration loading preserves default < ENV < runtime < call."""
    missing_runtime_path = tmp_path / "no-runtime-config.json"
    runtime_path = tmp_path / "runtime-config.json"
    runtime_path.write_text(
        json.dumps({"version": 1, "values": {"cache_max_items": 7}}),
        encoding="utf-8",
    )
    # Each observation has a complete input set, so a preceding assertion or a
    # developer-local runtime file cannot determine another level's result.
    monkeypatch.delenv("KOKORO_CACHE_MAX_ITEMS", raising=False)
    monkeypatch.setenv("ANGEVOICE_RUNTIME_CONFIG_FILE", str(missing_runtime_path))
    default_value = TTSConfig().cache_max_items
    default_config = load_config()
    assert default_config.cache_max_items == default_value

    monkeypatch.setenv("KOKORO_CACHE_MAX_ITEMS", "5")
    env_config = load_config()
    assert env_config.cache_max_items == 5

    monkeypatch.setenv("ANGEVOICE_RUNTIME_CONFIG_FILE", str(runtime_path))

    runtime_wins = load_config()
    assert runtime_wins.cache_max_items == 7

    call_wins = load_config(cache_max_items=9)
    assert call_wins.cache_max_items == 9


def test_registry_declares_stable_capabilities_without_constructing_runtimes() -> None:
    cfg = TTSConfig(
        enabled_models=["kokoro", "moss", "zipvoice"],
        moss_cuda_enabled=False,
        moss_execution_provider="cpu",
        zipvoice_execution_provider="cpu",
    )
    registry = EngineRegistry()
    specs = {spec.id: spec for spec in registry.list_specs(cfg)}
    assert set(specs) == {"kokoro", "moss", "zipvoice"}

    capabilities = {model_id: registry.capabilities_for(spec, cfg) for model_id, spec in specs.items()}
    assert capabilities["kokoro"].stream_mode == "segmented"
    assert capabilities["kokoro"].speed_supported is True
    assert capabilities["moss"].stream_mode == "native"
    assert capabilities["moss"].voice_clone_supported is True
    assert capabilities["zipvoice"].requires_prompt_audio is True
    assert capabilities["zipvoice"].supports_saved_voice_profiles is True
