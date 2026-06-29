from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from kokoro_tts.config import TTSConfig
from kokoro_tts.routes.ws import TtsWebSocketSession, WsSessionState


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

