from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from kokoro_tts.config import TTSConfig
from kokoro_tts.routes.ws import TtsWebSocketSession, WsSessionState


@pytest.mark.parametrize("failure", ["validation", "resource"])
def test_first_message_failure_preserves_error_and_cleans_saved_reference(monkeypatch, tmp_path, failure):
    from fastapi import HTTPException
    import kokoro_tts.ws.session as module
    import kokoro_tts.prompt_audio as prompt_audio

    async def run():
        state = _fake_state()
        state.cfg.stream_enabled = True
        state.model_manager.normalize_model_id.return_value = "zipvoice"
        state.voice_profiles.upload_limit_bytes.return_value = 1024
        monkeypatch.setattr(prompt_audio, "prompt_audio_temp_dir", lambda: tmp_path)
        monkeypatch.setattr(module, "verify_ws_key", AsyncMock(return_value=True))
        error = HTTPException(422, "参考音频时长超限") if failure == "validation" else OSError("private resource")
        monkeypatch.setattr(module, "validate_reference_audio_duration", MagicMock(side_effect=error))
        websocket = MagicMock(query_params={}, headers={})
        websocket.accept = AsyncMock()
        websocket.close = AsyncMock()
        websocket.send_json = AsyncMock()
        session = TtsWebSocketSession(websocket=websocket, state=state)
        session._receive_json_limited = AsyncMock(return_value={"text": "你好", "prompt_audio_data": "YQ=="})
        await session.run()
        message = websocket.send_json.call_args.args[0]
        assert message["type"] == "error"
        assert message["request_id"] == "req-2615"
        assert message["message"] == ("参考音频时长超限" if failure == "validation" else "参考音频处理失败")
        assert session.prompt_audio_path is not None
        assert list(tmp_path.iterdir()) == []
        websocket.close.assert_awaited_once()
        state.streaming.build_request.assert_not_called()
        state.streaming.iter_frames.assert_not_called()

    asyncio.run(run())


def test_binary_stream_preserves_metadata_audio_order_and_error_terminal():
    async def run():
        state = _fake_state()
        sent = []
        websocket = MagicMock()
        websocket.send_json = AsyncMock(side_effect=lambda value: sent.append(("json", value)))
        websocket.send_bytes = AsyncMock(side_effect=lambda value: sent.append(("bytes", value)))
        session = TtsWebSocketSession(websocket=websocket, state=state)
        await session.queue.put({"type": "audio", "data": "YWI=", "index": 2})
        await session.queue.put({"type": "segment_error", "message": "failure"})
        await session.queue.put({"type": "done"})
        await session.queue.put(session.done_marker)
        await session._send_loop(binary=True)
        assert sent == [
            ("json", {"type": "audio", "index": 2, "request_id": "req-2615"}),
            ("bytes", b"ab"),
            ("json", {"type": "segment_error", "message": "failure", "request_id": "req-2615"}),
            ("json", {"type": "done", "request_id": "req-2615"}),
        ]
        assert session.saw_stream_error and session.saw_stream_terminal
        state.inc_stat.assert_called_once_with("requests_error")
        state.request_cancel.assert_not_called()

    asyncio.run(run())


@pytest.mark.parametrize("data", ["%%%", "非ASCII编码"])
def test_binary_stream_invalid_encoding_stops_before_audio_or_following_frames(data):
    async def run():
        state = _fake_state()
        websocket = MagicMock()
        websocket.send_json = AsyncMock()
        websocket.send_bytes = AsyncMock()
        session = TtsWebSocketSession(websocket=websocket, state=state)
        await session.queue.put({"type": "audio", "data": data})
        await session.queue.put({"type": "done"})
        await session._send_loop(binary=True)
        websocket.send_json.assert_awaited_once_with({"type": "error", "message": "流式音频帧无效", "request_id": "req-2615"})
        websocket.send_bytes.assert_not_awaited()
        state.inc_stat.assert_called_once_with("requests_error")
        assert session.queue.qsize() == 1

    asyncio.run(run())


@pytest.mark.parametrize("reference", [
    {"prompt_audio": {"data": "YWI=", "filename": "voice.wav"}},
    {"prompt_audio_data": "YWI="},
    {"reference_audio_data": "YWI="},
    {},
])
def test_first_message_aliases_reach_service_and_reference_is_session_owned(monkeypatch, tmp_path, reference):
    import kokoro_tts.ws.session as module
    import kokoro_tts.prompt_audio as prompt_audio

    async def run():
        state = _fake_state()
        state.model_manager.normalize_model_id.return_value = "moss"
        state.model_manager.get_engine.return_value.default_voice = "engine-default"
        state.voice_profiles.upload_limit_bytes.return_value = 1024
        monkeypatch.setattr(prompt_audio, "prompt_audio_temp_dir", lambda: tmp_path)
        monkeypatch.setattr(module, "verify_ws_key", AsyncMock(return_value=True))
        websocket = MagicMock(query_params={}, headers={})
        websocket.accept = AsyncMock()
        websocket.close = AsyncMock()
        session = TtsWebSocketSession(websocket=websocket, state=state)
        message = {"text": "日期2026年", "tn_engine": "builtin", "engine_params": {"steps": 8}, "binary": True, **reference}
        session._receive_json_limited = AsyncMock(return_value=message)
        observed = []

        async def stream(request):
            values = state.streaming.build_request.call_args.kwargs
            observed.append(values)
            assert request is state.streaming.build_request.return_value
            if reference:
                from pathlib import Path
                assert Path(values["prompt_audio_path"]).read_bytes() == b"ab"
                assert values["prompt_audio_id"].startswith("sha256:")
            else:
                assert values["prompt_audio_path"] is None

        session._stream = stream
        await session.run()
        assert len(observed) == 1
        assert observed[0]["text"] == "日期2026年"
        assert observed[0]["text_normalization"] == "builtin"
        assert observed[0]["voice"] == "engine-default"
        assert observed[0]["engine_params"] == {"steps": 8}
        assert observed[0]["parameter_source"] is message
        assert observed[0]["binary"] == state.cfg.stream_binary_enabled
        assert list(tmp_path.iterdir()) == []
        websocket.close.assert_awaited_once()

    asyncio.run(run())


def _fake_condition() -> SimpleNamespace:
    return SimpleNamespace(
        is_reference_conditioned=False,
        prompt_audio_id="",
        revision="",
        as_dict=lambda: {},
    )


def _fake_streaming_request(**overrides) -> SimpleNamespace:
    data = {
        "model_id": "kokoro",
        "text": "你好",
        "voice": "zm_010",
        "audio_format": "pcm_s16le",
        "binary": False,
        "condition": _fake_condition(),
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _fake_state() -> MagicMock:
    state = MagicMock()
    state.cfg = TTSConfig(request_timeout_seconds=2, websocket_stream_idle_timeout_seconds=2)
    state.new_request_id.return_value = "req-2615"
    state.tts_semaphore = asyncio.Semaphore(1)
    state.is_cancelled.return_value = False
    state.streaming.iter_frames.return_value = iter([{"type": "done", "total_audio_chunks": 0}])
    return state


@pytest.mark.parametrize("ending", ["queue-stop", "failure", "http-error", "cancel", "done"])
@pytest.mark.parametrize("close_fails", [False, True])
def test_producer_closes_owned_iterator_before_end_notice(ending, close_fails):
    from fastapi import HTTPException

    state = _fake_state()
    session = TtsWebSocketSession(websocket=MagicMock(), state=state)
    session.loop = MagicMock()
    session.loop.is_closed.return_value = False
    events = []
    consumed = []

    def frames():
        consumed.append("first")
        yield {"type": "audio", "data": "first"}
        if ending == "failure":
            raise RuntimeError("engine failed")
        if ending == "http-error":
            raise HTTPException(400, "bad parameter")
        if ending == "cancel":
            session.cancel_event.set()
        consumed.append("late")
        yield {"type": "audio", "data": "late"}
        yield {"type": "done"}

    class OwnedIterator:
        def __init__(self):
            self.inner = frames()
            self.closes = 0

        def __iter__(self):
            return self

        def __next__(self):
            return next(self.inner)

        def close(self):
            self.closes += 1
            self.inner.close()
            events.append("closed")
            if close_fails:
                raise RuntimeError("cleanup failed")

    iterator = OwnedIterator()  # Retained: cleanup must not depend on reference counting.
    state.streaming.iter_frames.return_value = iterator

    def put(frame):
        events.append(frame)
        return ending != "queue-stop"

    session._thread_put = put
    session._producer(_fake_streaming_request())
    assert iterator.closes == 1
    assert consumed == (["first"] if ending in {"queue-stop", "failure", "http-error"} else ["first", "late"])
    if ending == "cancel":
        assert events == [{"type": "audio", "data": "first"}, "closed"]
        session.loop.call_soon_threadsafe.assert_called_once_with(session._schedule_cancelled_notice)
    else:
        assert events[-2:] == ["closed", session.done_marker]
        session.loop.call_soon_threadsafe.assert_not_called()
    errors = [frame for frame in events if isinstance(frame, dict) and frame.get("type") == "error"]
    if ending in {"failure", "http-error"}:
        assert len(errors) == 1
        assert errors[0]["message"] == ("bad parameter" if ending == "http-error" else "流式合成失败")
    else:
        assert errors == []


def test_producer_queue_stop_releases_service_borrow_before_notice():
    from contextlib import contextmanager
    from kokoro_tts.services.streaming_service import StreamingService

    state = _fake_state()
    events = []

    class Engine:
        def synthesize_stream(self, *args, **kwargs):
            try:
                yield {"type": "audio", "data": "AA=="}
                pytest.fail("queue failure must stop model consumption")
            finally:
                events.append("engine-closed")

    @contextmanager
    def borrow(model):
        assert model == "kokoro"
        events.append("borrowed")
        try:
            yield Engine()
        finally:
            events.append("released")

    state.model_manager.borrow.side_effect = borrow
    service = StreamingService(state)
    retained = []

    def iter_frames(request, **kwargs):
        frames = service.iter_frames(request, **kwargs)
        retained.append(frames)
        return frames

    state.streaming.iter_frames.side_effect = iter_frames
    session = TtsWebSocketSession(websocket=MagicMock(), state=state)
    session.loop = MagicMock()

    def put(frame):
        if frame is session.done_marker:
            events.append("notice")
        return False

    session._thread_put = put
    session._producer(_fake_streaming_request(
        request_id="req-2615", speed=1.0,
        condition=SimpleNamespace(prompt_audio_path=None, prompt_text=""),
        generation=SimpleNamespace(as_dict=lambda: {}),
    ))
    assert len(retained) == 1
    assert events == ["borrowed", "engine-closed", "released", "notice"]
    assert list(retained[0]) == []


def test_2615_ws_cancel_drains_late_audio_and_sends_single_cancel_terminal():
    async def run():
        state = _fake_state()
        session = TtsWebSocketSession(websocket=MagicMock(), state=state)
        await session.queue.put({"type": "audio", "data": "late-audio"})

        await session._mark_client_cancelled()
        await session._mark_client_cancelled()

        first = await session.queue.get()
        second = await session.queue.get()
        assert first == {"type": "cancelled", "request_id": "req-2615"}
        assert second is session.done_marker
        assert session.queue.empty()
        assert session.cancelled_by_client is True
        assert session.cancel_event.is_set() is True
        assert session.phase == WsSessionState.CANCELLING
        assert session.cancel_notified is True

    asyncio.run(run())


def test_2615_ws_stream_success_finishes_request_and_releases_background_tasks():
    async def run():
        state = _fake_state()
        websocket = MagicMock()
        websocket.send_json = AsyncMock()
        session = TtsWebSocketSession(websocket=websocket, state=state)

        async def idle_control_listener():
            await asyncio.sleep(60)

        session._control_listener = idle_control_listener  # type: ignore[method-assign]
        await session._stream(_fake_streaming_request())

        state.mark_request.assert_any_call(
            "req-2615",
            "queued",
            voice="zm_010",
            format="pcm_s16le",
            model="kokoro",
            chars=2,
            websocket=True,
            voice_clone=False,
            prompt_audio_id="",
            profile_revision="",
            voice_condition={},
        )
        state.mark_request.assert_any_call("req-2615", "running")
        state.finish_request.assert_called_once()
        assert state.finish_request.call_args.args[:2] == ("req-2615", "done")
        state.inc_stat.assert_any_call("requests_ok")
        assert session.phase == WsSessionState.DONE

    asyncio.run(run())


def test_2615_ws_stream_pre_cancel_finishes_cancelled_without_model_output():
    async def run():
        state = _fake_state()
        state.is_cancelled.return_value = True
        session = TtsWebSocketSession(websocket=MagicMock(), state=state)

        await session._stream(_fake_streaming_request())

        state.streaming.iter_frames.assert_not_called()
        state.finish_request.assert_called_once_with("req-2615", "cancelled")

    asyncio.run(run())


def test_2615_ws_send_failure_marks_cancelled_disconnect_cleanup():
    async def run():
        state = _fake_state()
        websocket = MagicMock()
        websocket.send_json = AsyncMock(side_effect=RuntimeError("client disconnected"))
        session = TtsWebSocketSession(websocket=websocket, state=state)
        await session.queue.put({"type": "audio", "data": "chunk"})

        await session._send_loop(binary=False)

        state.request_cancel.assert_called_once_with("req-2615")
        assert session.cancel_event.is_set() is True
        assert session.cancelled_by_client is True
        assert session.phase == WsSessionState.CANCELLING

    asyncio.run(run())


def test_2615_ws_finish_maps_cancelled_and_error_terminal_states():
    state = _fake_state()
    session = TtsWebSocketSession(websocket=MagicMock(), state=state)
    session.cancelled_by_client = True
    session._finish(time.perf_counter())
    assert state.finish_request.call_args.args[:2] == ("req-2615", "cancelled")

    state = _fake_state()
    session = TtsWebSocketSession(websocket=MagicMock(), state=state)
    session.saw_stream_error = True
    session._finish(time.perf_counter())
    assert state.finish_request.call_args.args[:2] == ("req-2615", "error")

