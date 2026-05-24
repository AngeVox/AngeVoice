"""Architecture contracts, services, policy, and route-boundary tests."""

from __future__ import annotations

import base64
from pathlib import Path
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from kokoro_tts.config import TTSConfig
from kokoro_tts.contracts import VoiceConditionKind
from kokoro_tts.engine_manager import EngineManager
from kokoro_tts.server import create_app
from kokoro_tts.service_state import ServiceState


def _cfg(tmp_path: Path) -> TTSConfig:
    return TTSConfig(
        enabled_models=["kokoro", "moss-nano-cpu", "zipvoice"],
        default_model="kokoro",
        moss_cuda_enabled=False,
        zipvoice_profiles_dir=tmp_path / "prompts" / "zipvoice",
        zipvoice_model_root=tmp_path / "models" / "zipvoice",
        zipvoice_distill_dir=tmp_path / "models" / "zipvoice" / "zipvoice_distill",
        zipvoice_vocos_dir=tmp_path / "models" / "zipvoice" / "vocos-mel-24khz",
        model_idle_timeout_seconds=0,
    )


def test_voice_profile_service_is_single_owner_for_profile_adapter(tmp_path):
    manager = EngineManager(_cfg(tmp_path))
    state = ServiceState(_cfg(tmp_path), model_manager=manager)
    try:
        engine = manager.get_engine("zipvoice", load=False)
        assert engine.profiles is state.voice_profiles.store_for("zipvoice")
        state.voice_profiles.save("zipvoice", voice_id="voice_a", prompt_text="参考文本", audio_bytes=b"RIFF-a")
        request = state.synthesis.build_request(
            text="正文", voice="voice_a", speed=1.0, response_format="wav", model_id="zipvoice"
        )
        assert request.condition.kind is VoiceConditionKind.SAVED_PROFILE
        assert request.condition.prompt_text == "参考文本"
        assert request.condition.prompt_audio_path.endswith("/voice_a/reference.wav")
    finally:
        manager.stop_idle_timer()


def test_dynamic_parameter_schema_accepts_generic_and_legacy_controls(tmp_path):
    manager = EngineManager(_cfg(tmp_path))
    state = ServiceState(_cfg(tmp_path), model_manager=manager)
    try:
        parsed = state.parameter_schema.parse(
            "zipvoice",
            {"zipvoice_num_steps": "12", "zipvoice_remove_long_sil": "true"},
            supplied={"unknown": "ignored"},
        )
        assert parsed == {"zipvoice_num_steps": 12, "zipvoice_remove_long_sil": True}
        override = state.parameter_schema.parse(
            "zipvoice", {"zipvoice_num_steps": "8"}, supplied={"zipvoice_num_steps": 12}
        )
        assert override["zipvoice_num_steps"] == 12
        zipvoice = next(item for item in manager.list_models() if item["id"] == "zipvoice")
        assert {item["key"] for item in zipvoice["parameter_schema"]} == {"zipvoice_num_steps", "zipvoice_remove_long_sil"}
        assert zipvoice["provider_policy"]["cpu_release_default"] is True
    finally:
        manager.stop_idle_timer()


def test_streaming_service_passes_resolved_profile_and_schema_controls_to_adapter(tmp_path):
    manager = EngineManager(_cfg(tmp_path))
    state = ServiceState(_cfg(tmp_path), model_manager=manager)
    state.voice_profiles.save("zipvoice", voice_id="voice_ws", prompt_text="对应参考文本", audio_bytes=b"RIFF-ws")

    class FakeStreamAdapter:
        is_loaded = True
        is_healthy = True

        def __init__(self):
            self.received = None

        def synthesize_stream(self, text, voice="", speed=1.0, fmt="pcm_s16le", *, prompt_audio_path=None, prompt_text="", cancel_check=None, zipvoice_num_steps=None):
            self.received = (prompt_audio_path, prompt_text, zipvoice_num_steps, bool(cancel_check))
            yield {"type": "audio", "data": base64.b64encode(b"\x00\x00").decode("ascii")}
            yield {"type": "done", "total_audio_chunks": 1}

    fake = FakeStreamAdapter()
    manager._engines["zipvoice"] = fake
    try:
        request = state.streaming.build_request(
            text="流式正文。", model_id="zipvoice", voice="voice_ws", speed=1.0,
            audio_format="pcm_s16le", binary=False, engine_params={"zipvoice_num_steps": 12}, request_id="req1",
        )
        frames = list(state.streaming.iter_frames(request, cancel_check=lambda: False))
        assert fake.received[0].endswith("/voice_ws/reference.wav")
        assert fake.received[1:] == ("对应参考文本", 12, True)
        assert frames[0]["model"] == "zipvoice"
        assert frames[0]["request_id"] == "req1"
    finally:
        manager.stop_idle_timer()


def test_runtime_resource_contract_includes_active_request_status(tmp_path):
    manager = EngineManager(_cfg(tmp_path))
    state = ServiceState(_cfg(tmp_path), model_manager=manager)
    try:
        state.mark_request("busy", "running", model="kokoro")
        resources = state.resource_snapshot()
        assert resources["active_requests"] == 1
        assert {"rss_bytes", "cache_items", "models", "current_model", "sampled_at"}.issubset(resources)
    finally:
        manager.stop_idle_timer()


def test_parameter_schema_endpoint_exposes_engine_driven_controls(tmp_path):
    initial = MagicMock()
    initial.is_loaded = True
    initial.is_healthy = True
    initial.get_voices.return_value = ["zm_010"]
    initial.default_voice = "zm_010"
    initial.metadata.return_value = {"id": "kokoro", "loaded": True, "voice_clone_supported": False}
    app = create_app(config=_cfg(tmp_path), engine=initial)
    with TestClient(app) as client:
        response = client.get("/v1/engines/parameter-schema")
    assert response.status_code == 200
    assert response.json()["schemas"]["zipvoice"][0]["key"] == "zipvoice_num_steps"
    app.state.angevoice.model_manager.stop_idle_timer()


def test_routes_depend_on_services_not_zipvoice_private_or_signature_branches():
    root = Path(__file__).resolve().parents[1] / "src" / "kokoro_tts" / "routes"
    ws_source = (root / "ws.py").read_text(encoding="utf-8")
    audio_source = (root / "audio.py").read_text(encoding="utf-8")
    assert "_zipvoice_prompt_context" not in ws_source
    assert "inspect.signature" not in ws_source
    assert "_zipvoice_generation_params" not in audio_source
    assert "state.streaming" in ws_source
    assert "state.synthesis" in audio_source


def test_frontend_renders_engine_parameter_schema_without_hardcoded_fields():
    root = Path(__file__).resolve().parents[1] / "src" / "kokoro_tts"
    js = (root / "static" / "app.js").read_text(encoding="utf-8")
    html = (root / "templates" / "index.html").read_text(encoding="utf-8")
    assert "model?.parameter_schema" in js
    assert "collectEngineParams" in js
    assert "engine-parameter-fields" in html
