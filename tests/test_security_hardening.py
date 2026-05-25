"""Security and concurrency regression tests."""

from __future__ import annotations

import base64
import os
import time

import pytest
from pathlib import Path
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from kokoro_tts.config import TTSConfig
from kokoro_tts.config_api_key import effective_api_key
from kokoro_tts.prompt_audio import PROMPT_AUDIO_STALE_SECONDS, save_prompt_audio_bytes
from kokoro_tts.routes.admin_runtime import rotate_api_key
from kokoro_tts.server import create_app
from kokoro_tts.service_state import ServiceState


def _basic(username: str = "admin", password: str = "admin123") -> dict[str, str]:
    value = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {value}"}


def _fake_engine() -> MagicMock:
    engine = MagicMock()
    engine.is_loaded = True
    engine.is_healthy = True
    engine.get_voices.return_value = ["zm_010"]
    engine.default_voice = "zm_010"
    engine.metadata.return_value = {"id": "kokoro", "loaded": True, "voice_clone_supported": False}
    return engine


def test_api_key_rotation_uses_durable_file_without_process_env_leak(monkeypatch, tmp_path):
    monkeypatch.setenv("KOKORO_API_KEY", "bootstrap-from-operator")
    cfg = TTSConfig(api_key="bootstrap-from-operator", api_key_file=tmp_path / "credentials" / ".angevoice-api-key")
    rotated = rotate_api_key(cfg)
    assert rotated.startswith("av_")
    assert os.environ["KOKORO_API_KEY"] == "bootstrap-from-operator"
    # A separate worker/config instance resolves the persisted rotated key.
    other_worker = TTSConfig(api_key="bootstrap-from-operator", api_key_file=cfg.api_key_file)
    assert effective_api_key(other_worker) == rotated


def test_admin_voice_upload_rejects_symlink_target_and_writes_regular_file(tmp_path):
    model_dir = tmp_path / "models"
    voices_dir = model_dir / "voices"
    voices_dir.mkdir(parents=True)
    outside = tmp_path / "outside.pt"
    outside.write_bytes(b"outside")
    (voices_dir / "evil.pt").symlink_to(outside)
    cfg = TTSConfig(model_dir=model_dir, admin_enabled=True, voice_upload_enabled=True)
    client = TestClient(create_app(config=cfg, engine=_fake_engine()))
    rejected = client.post("/admin/voices/upload", headers=_basic(), files={"file": ("evil.pt", b"malicious", "application/octet-stream")})
    assert rejected.status_code == 409
    assert outside.read_bytes() == b"outside"
    accepted = client.post("/admin/voices/upload", headers=_basic(), files={"file": ("custom.pt", b"voice", "application/octet-stream")})
    assert accepted.status_code == 200
    assert (voices_dir / "custom.pt").read_bytes() == b"voice"
    assert "path" not in accepted.json()


def test_prompt_audio_cleanup_removes_only_stale_temp_files(monkeypatch, tmp_path):
    import kokoro_tts.prompt_audio as module
    monkeypatch.setattr(module.tempfile, "gettempdir", lambda: str(tmp_path))
    temp_dir = tmp_path / "angevoice_prompt_audio"
    temp_dir.mkdir()
    stale = temp_dir / "abandoned.wav"
    fresh = temp_dir / "keep.wav"
    stale.write_bytes(b"old")
    fresh.write_bytes(b"new")
    old = time.time() - PROMPT_AUDIO_STALE_SECONDS - 10
    os.utime(stale, (old, old))
    path, _ = save_prompt_audio_bytes(content=b"audio", filename="sample.wav", request_id="req", max_bytes=1024)
    assert path and Path(path).exists()
    assert not stale.exists()
    assert fresh.exists()


def test_websocket_cancellation_uses_threading_event():
    from kokoro_tts.routes.ws import TtsWebSocketSession
    state = MagicMock()
    state.cfg = TTSConfig()
    state.new_request_id.return_value = "req"
    session = TtsWebSocketSession(websocket=MagicMock(), state=state)
    assert hasattr(session, "cancel_event")
    assert not hasattr(session, "cancel_flag")
    session.cancel_event.set()
    assert session.cancel_event.is_set()


def test_multipart_prompt_audio_upload_streams_in_chunks_and_enforces_cap(monkeypatch, tmp_path):
    import asyncio
    import kokoro_tts.prompt_audio as module
    from fastapi import HTTPException

    monkeypatch.setattr(module.tempfile, "gettempdir", lambda: str(tmp_path))

    class Upload:
        def __init__(self, payload: bytes):
            self.payload = payload
            self.offset = 0
            self.calls: list[int] = []

        async def read(self, size: int):
            self.calls.append(size)
            chunk = self.payload[self.offset:self.offset + size]
            self.offset += len(chunk)
            return chunk

    upload = Upload(b"a" * 17)
    path, digest = asyncio.run(module.save_prompt_audio_upload(
        upload=upload, filename="sample.wav", request_id="streamed", max_bytes=32, chunk_bytes=8
    ))
    assert path and Path(path).read_bytes() == b"a" * 17
    assert digest.startswith("sha256:")
    assert len(upload.calls) >= 3

    oversized = Upload(b"b" * 33)
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(module.save_prompt_audio_upload(
            upload=oversized, filename="sample.wav", request_id="too-large", max_bytes=32, chunk_bytes=8
        ))
    assert exc_info.value.status_code == 413


def test_websocket_binary_audio_frame_without_data_is_reported_not_crashed():
    import asyncio
    from unittest.mock import AsyncMock
    from kokoro_tts.routes.ws import TtsWebSocketSession

    state = MagicMock()
    state.cfg = TTSConfig(request_timeout_seconds=2)
    state.new_request_id.return_value = "req-frame"
    websocket = MagicMock()
    websocket.send_json = AsyncMock()
    websocket.send_bytes = AsyncMock()
    session = TtsWebSocketSession(websocket=websocket, state=state)

    async def run():
        await session.queue.put({"type": "audio"})
        await session._send_loop(binary=True)

    asyncio.run(run())
    websocket.send_bytes.assert_not_awaited()
    sent = websocket.send_json.await_args.args[0]
    assert sent["type"] == "error"
    assert sent["request_id"] == "req-frame"
    assert session.saw_stream_error is True


def test_request_snapshot_returns_recent_copy_and_pruning_works_outside_callers():
    state = ServiceState(TTSConfig(queue_status_enabled=True))
    for idx in range(121):
        state.mark_request(f"req-{idx}", "done", updated_at=float(idx))
    state.finish_request("req-120", "done", updated_at=120.0)
    values = state.request_snapshot(limit=3)
    assert [item["id"] for item in values] == ["req-120", "req-119", "req-118"]
    assert len(state.request_snapshot()) <= 101


def test_websocket_prompt_audio_base64_rejects_oversized_payload_before_decode(monkeypatch):
    import kokoro_tts.prompt_audio as module
    from fastapi import HTTPException

    called = False

    def should_not_decode(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("oversized payload must be rejected before base64 allocation")

    monkeypatch.setattr(module.base64, "b64decode", should_not_decode)
    with pytest.raises(HTTPException) as exc_info:
        module.decode_prompt_audio_base64("Y" * 12, max_bytes=4)
    assert exc_info.value.status_code == 413
    assert called is False


def test_vendor_seedtts_reads_test_list_with_context_manager():
    source = (Path(__file__).resolve().parents[1] / "vendor/ZipVoice/zipvoice/eval/wer/seedtts.py").read_text(encoding="utf-8")
    assert 'with open(test_list, encoding="utf-8") as test_file:' in source
    assert "for line in open(test_list).readlines()" not in source


def test_websocket_multiple_error_frames_count_only_one_failed_request():
    import asyncio
    from unittest.mock import AsyncMock
    from kokoro_tts.routes.ws import TtsWebSocketSession

    state = MagicMock()
    state.cfg = TTSConfig(request_timeout_seconds=2)
    state.new_request_id.return_value = "req-double-error"
    websocket = MagicMock()
    websocket.send_json = AsyncMock()
    websocket.send_bytes = AsyncMock()
    session = TtsWebSocketSession(websocket=websocket, state=state)

    async def run():
        await session.queue.put({"type": "segment_error", "message": "first"})
        await session.queue.put({"type": "error", "message": "second"})
        await session.queue.put(session.done_marker)
        await session._send_loop(binary=False)

    asyncio.run(run())
    calls = [call for call in state.inc_stat.call_args_list if call.args and call.args[0] == "requests_error"]
    assert len(calls) == 1
    assert session.saw_stream_error is True


def test_request_history_pruning_never_removes_running_request():
    state = ServiceState(TTSConfig(queue_status_enabled=True))
    state.mark_request("long-running", "running", updated_at=-1.0)
    for idx in range(120):
        state.mark_request(f"done-{idx}", "done", updated_at=float(idx))
    state.finish_request("done-119", "done", updated_at=119.0)
    snapshot = {item["id"]: item for item in state.request_snapshot()}
    assert "long-running" in snapshot
    assert snapshot["long-running"]["status"] == "running"

def test_websocket_cancel_notice_is_not_created_when_event_loop_rejects_scheduling(monkeypatch):
    from kokoro_tts.routes.ws import TtsWebSocketSession

    state = MagicMock()
    state.cfg = TTSConfig(request_timeout_seconds=2)
    state.new_request_id.return_value = "req-loop-closed"
    state.streaming.iter_frames.return_value = []
    session = TtsWebSocketSession(websocket=MagicMock(), state=state)
    session.cancel_event.set()
    session.loop = MagicMock()
    session.loop.is_closed.return_value = False
    session.loop.call_soon_threadsafe.side_effect = RuntimeError("event loop is closed")

    notify = MagicMock()
    monkeypatch.setattr(session, "_notify_cancelled", notify)
    session._producer(MagicMock())

    session.loop.call_soon_threadsafe.assert_called_once_with(session._schedule_cancelled_notice)
    notify.assert_not_called()



def test_websocket_query_token_authenticates_before_payload_and_keeps_legacy_payload_shape():
    engine = _fake_engine()
    engine.synthesize_stream.return_value = iter([{"type": "done", "total_segments": 0, "total_audio_chunks": 0}])
    cfg = TTSConfig(api_key="secret-token")
    app = create_app(config=cfg, engine=engine)
    with TestClient(app) as client:
        with client.websocket_connect("/ws/v1/tts?token=secret-token") as ws:
            ws.send_json({"text": "测试", "voice": "zm_010", "format": "pcm_s16le"})
            frame = ws.receive_json()
    assert frame["type"] == "done"


def test_websocket_invalid_query_token_is_rejected_without_processing_request():
    from starlette.websockets import WebSocketDisconnect

    cfg = TTSConfig(api_key="secret-token")
    app = create_app(config=cfg, engine=_fake_engine())
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/ws/v1/tts?token=wrong"):
                pass
    assert exc.value.code == 1008


def test_websocket_preauth_does_not_reject_when_api_key_is_not_configured():
    """A supplied query token must not create an auth requirement on an open service."""
    engine = _fake_engine()
    engine.synthesize_stream.return_value = iter([{"type": "done", "total_segments": 0, "total_audio_chunks": 0}])
    cfg = TTSConfig(api_key=None)
    app = create_app(config=cfg, engine=engine)
    with TestClient(app) as client:
        with client.websocket_connect("/ws/v1/tts?token=ignored-when-auth-disabled") as ws:
            ws.send_json({"text": "测试", "voice": "zm_010", "format": "pcm_s16le"})
            frame = ws.receive_json()
    assert frame["type"] == "done"


def test_websocket_preauth_uses_persisted_key_even_when_cfg_api_key_is_none(tmp_path):
    """Pre-auth resolves the effective persisted key instead of reading cfg.api_key only."""
    engine = _fake_engine()
    engine.synthesize_stream.return_value = iter([{"type": "done", "total_segments": 0, "total_audio_chunks": 0}])
    key_file = tmp_path / ".angevoice-api-key"
    key_file.write_text("persisted-token\n", encoding="utf-8")
    cfg = TTSConfig(api_key=None, api_key_file=key_file)
    app = create_app(config=cfg, engine=engine)
    with TestClient(app) as client:
        with client.websocket_connect("/ws/v1/tts?token=persisted-token") as ws:
            ws.send_json({"text": "测试", "voice": "zm_010", "format": "pcm_s16le"})
            frame = ws.receive_json()
    assert frame["type"] == "done"


def test_websocket_message_budget_rejects_oversized_json_without_starting_engine():
    from starlette.websockets import WebSocketDisconnect

    engine = _fake_engine()
    cfg = TTSConfig(websocket_max_message_bytes=1024, rate_limit_qps=0, max_queue_length=0)
    app = create_app(config=cfg, engine=engine)
    with TestClient(app) as client:
        with client.websocket_connect("/ws/v1/tts") as ws:
            ws.send_json({"text": "超" * 2048, "voice": "zm_010", "format": "pcm_s16le"})
            frame = ws.receive_json()
            assert frame["type"] == "error"
            assert "过大" in frame["message"]
    engine.synthesize_stream.assert_not_called()


def test_websocket_connection_gate_rejects_excess_idle_sessions():
    from starlette.websockets import WebSocketDisconnect

    cfg = TTSConfig(websocket_max_connections=1, rate_limit_qps=0, max_queue_length=0, request_timeout_seconds=30)
    app = create_app(config=cfg, engine=_fake_engine())
    with TestClient(app) as client:
        with client.websocket_connect("/ws/v1/tts"):
            with pytest.raises(WebSocketDisconnect) as exc:
                with client.websocket_connect("/ws/v1/tts"):
                    pass
            assert exc.value.code == 1013
    assert app.state.angevoice.snapshot_stats()["ws_connections_rejected_total"] == 1


def test_external_bind_without_api_key_warns_but_remains_supported(caplog):
    cfg = TTSConfig(host="0.0.0.0", api_key=None)
    with caplog.at_level("WARNING"):
        cfg.validate_security()
    assert "API authentication is disabled" in caplog.text


def test_loopback_bind_without_api_key_does_not_warn(caplog):
    cfg = TTSConfig(host="127.0.0.1", api_key=None)
    with caplog.at_level("WARNING"):
        cfg.validate_security()
    assert "API authentication is disabled" not in caplog.text
