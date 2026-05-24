"""Phase 1 product-model registry and legacy alias compatibility checks."""

from unittest.mock import MagicMock

from kokoro_tts.config import TTSConfig
from kokoro_tts.engine_manager import EngineManager
from kokoro_tts.engines.registry import EngineRegistry
from kokoro_tts.service_state import ServiceState


def test_public_catalog_collapses_legacy_moss_variants_to_one_product_model():
    cfg = TTSConfig(
        enabled_models=["kokoro", "moss-nano-cpu", "moss-nano-cuda"],
        default_model="kokoro",
        moss_execution_provider="cpu",
        moss_cuda_enabled=True,
    )
    manager = EngineManager(cfg)
    try:
        assert [spec.id for spec in manager.list_specs()] == ["kokoro", "moss"]
        models = manager.list_models()
        assert [model["id"] for model in models] == ["kokoro", "moss"]
        moss = next(model for model in models if model["id"] == "moss")
        assert moss["voice_clone_supported"] is True
        assert moss["speed_supported"] is False
    finally:
        manager.stop_idle_timer()


def test_legacy_moss_aliases_resolve_to_public_model_with_provider_hints():
    registry = EngineRegistry()
    cpu = registry.resolve("moss-nano-cpu")
    cuda = registry.resolve("moss-gpu")
    generic = registry.resolve("moss")

    assert (cpu.canonical_id, cpu.provider_hint, cpu.deprecated_alias) == ("moss", "cpu", True)
    assert (cuda.canonical_id, cuda.provider_hint, cuda.deprecated_alias) == ("moss", "cuda", True)
    assert (generic.canonical_id, generic.provider_hint, generic.deprecated_alias) == ("moss", None, False)


def test_legacy_moss_cpu_request_can_borrow_canonical_engine_without_loading_runtime(monkeypatch):
    cfg = TTSConfig(enabled_models=["kokoro", "moss-nano-cpu"], default_model="kokoro")
    manager = EngineManager(cfg)
    fake = MagicMock()
    fake.is_loaded = True
    fake.is_healthy = True
    fake.requested_provider = "cpu"
    fake.metadata.return_value = {"id": "moss", "actual_provider": "cpu"}
    manager._engines["moss"] = fake
    try:
        with manager.borrow("moss-nano-cpu") as engine:
            assert engine is fake
        assert manager.current_model_id == "moss"
    finally:
        manager.stop_idle_timer()


def test_canonical_moss_uses_configured_prompt_audio_for_cache_identity(tmp_path):
    prompt = tmp_path / "prompt.wav"
    prompt.write_bytes(b"audio")
    cfg = TTSConfig(enabled_models=["kokoro", "moss-nano-cpu"], default_model="kokoro", moss_prompt_audio_path=prompt)
    state = ServiceState(cfg)
    try:
        assert state.prompt_audio_cache_id("moss").startswith("path:")
    finally:
        state.model_manager.stop_idle_timer()


def test_switch_via_legacy_alias_reports_canonical_product_without_loading_model():
    cfg = TTSConfig(enabled_models=["kokoro", "moss-nano-cpu"], default_model="kokoro", moss_execution_provider="cpu")
    manager = EngineManager(cfg)
    try:
        result = manager.switch_model("moss-nano-cpu", unload_previous=False, load=False)
        assert result["current_model"] == "moss"
        assert result["canonical_model"] == "moss"
        assert result["requested_model"] == "moss-nano-cpu"
        assert result["deprecated_alias"] is True
        assert result["provider_hint"] == "cpu"
    finally:
        manager.stop_idle_timer()


def test_disabled_legacy_cuda_alias_is_not_silently_routed_to_cpu():
    from fastapi import HTTPException
    import pytest

    cfg = TTSConfig(enabled_models=["kokoro", "moss-nano-cpu"], default_model="kokoro", moss_cuda_enabled=False)
    manager = EngineManager(cfg)
    try:
        with pytest.raises(HTTPException) as exc:
            manager.get_engine("moss-nano-cuda", load=False)
        assert exc.value.status_code == 404
    finally:
        manager.stop_idle_timer()

async def _public_model_response():
    from httpx import ASGITransport, AsyncClient
    from kokoro_tts.server import create_app

    mock_engine = MagicMock()
    mock_engine.is_loaded = True
    mock_engine.is_healthy = True
    mock_engine.metadata.return_value = {"id": "kokoro", "loaded": True, "voices": ["zm_010"]}
    cfg = TTSConfig(enabled_models=["kokoro", "moss-nano-cpu"], default_model="kokoro")
    app = create_app(config=cfg, engine=mock_engine)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return (await client.get("/v1/models")).json()


async def test_v1_models_exposes_canonical_products_only():
    response = await _public_model_response()
    ids = [item["id"] for item in response["models"]]
    assert ids == ["kokoro", "moss"]
    assert "moss-nano-cpu" not in ids
    assert "zipvoice" not in ids
