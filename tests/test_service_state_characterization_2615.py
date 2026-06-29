from __future__ import annotations

from pathlib import Path

from kokoro_tts.config import TTSConfig
from kokoro_tts.service_state import ServiceState


def test_2615_service_state_facade_import_and_core_attributes_are_stable(tmp_path):
    cfg = TTSConfig(
        model_dir=tmp_path / "models",
        output_dir=tmp_path / "outputs",
        enabled_models=["kokoro"],
        default_model="kokoro",
        cache_max_items=2,
        queue_status_enabled=True,
    )
    state = ServiceState(cfg)

    assert state.cfg is cfg
    assert state.model_manager.current_model_id == "kokoro"
    assert hasattr(state, "voice_profiles")
    assert hasattr(state, "streaming")
    assert hasattr(state, "synthesis")
    assert hasattr(state, "runtime_resources")
    assert hasattr(state, "tts_semaphore")
    assert isinstance(state.tts_cache, dict)
    assert isinstance(state.active_requests, dict)
    assert isinstance(state.cancelled_requests, set)


def test_2615_service_state_cache_stats_and_resource_snapshot_shape(tmp_path):
    state = ServiceState(TTSConfig(model_dir=tmp_path, cache_enabled=True, cache_max_items=2, cache_max_bytes=6))

    assert state.cache_get("missing") is None
    state.cache_set("a", (b"1234", "audio/wav"), text="短文本")
    state.cache_set("b", (b"5678", "audio/wav"), text="短文本")

    assert state.cache_size() == 1
    assert state.cache_bytes() == 4
    assert state.cache_get("b") == (b"5678", "audio/wav")

    stats = state.snapshot_stats()
    assert stats["cache_misses"] == 1
    assert stats["cache_hits"] == 1

    resources = state.resource_snapshot()
    assert {"rss_bytes", "cache_items", "cache_bytes", "models", "current_model", "sampled_at"}.issubset(resources)
    assert resources["cache_items"] == 1


def test_2615_service_state_request_registry_cancel_and_pruning_contract():
    state = ServiceState(TTSConfig(queue_status_enabled=True))

    state.mark_request("running", "running", updated_at=-1.0)
    assert state.request_is_active("running") is True
    assert state.request_info("running")["status"] == "running"
    assert state.request_cancel("running") is True
    assert state.is_cancelled("running") is True
    assert state.request_info("running")["status"] == "cancelling"
    state.finish_request("running", "cancelled", elapsed_seconds=0.1)
    assert state.is_cancelled("running") is False

    for index in range(121):
        state.mark_request(f"done-{index}", "done", updated_at=float(index))
    state.finish_request("done-120", "done", updated_at=120.0)

    snapshot = state.request_snapshot(limit=3)
    assert snapshot[0]["id"] == "running"
    assert snapshot[0]["status"] == "cancelled"
    assert [item["id"] for item in snapshot[1:]] == ["done-120", "done-119"]
    full_snapshot = {item["id"]: item for item in state.request_snapshot()}
    assert "running" in full_snapshot
    assert full_snapshot["running"]["status"] == "cancelled"


def test_2615_service_state_output_save_contract(tmp_path):
    state = ServiceState(TTSConfig(output_dir=tmp_path / "outputs", save_outputs=True))

    saved = state.save_generated_output(
        request_id="req/unsafe",
        audio_bytes=b"RIFFdata",
        response_format="wav",
        media_type="audio/wav",
        model_id="kokoro",
        voice="zm_010",
    )

    assert isinstance(saved, Path)
    assert saved.exists()
    assert saved.name.endswith(".wav")
    assert "/" not in saved.name and "\\" not in saved.name
    assert saved.read_bytes() == b"RIFFdata"
