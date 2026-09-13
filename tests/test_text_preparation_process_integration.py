"""Real spawn/dispatcher coverage with a recording runtime, without model assets.

These tests complement the frozen text semantics contract. They prove transport
and request isolation, not inference, audio quality or native WeText behavior.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from kokoro_tts.engines.adapters.kokoro import KokoroAdapter
from kokoro_tts.moss_engine import MossNanoEngine
from kokoro_tts.workers import EngineProcessClient, EngineWorkerSpec

pytestmark = pytest.mark.integration
TEXT = "今天是2026-05-20，价格123.45元。"


class _RecordingEngine:
    def __init__(self):
        self.calls = 0

    def load(self):
        pass

    def unload(self):
        pass

    def metadata(self):
        return {"loaded": True, "pid": os.getpid()}

    def synthesize_array(self, text, *, text_prepared=False, **kwargs):
        self.calls += 1
        return {"text": text, "prepared": text_prepared, "pid": os.getpid(), "call": self.calls}

    def synthesize(self, **kwargs):
        return self.synthesize_array(**kwargs)

    def synthesize_stream(self, **kwargs):
        yield {"type": "observed", **self.synthesize_array(**kwargs)}
        yield {"type": "done", "total_segments": 1, "total_audio_chunks": 0}


def _recording_factory(_config, _provider):
    return _RecordingEngine()


@pytest.fixture
def worker():
    config = SimpleNamespace(
        request_timeout_seconds=15.0,
        engine_process_stream_idle_timeout_seconds=15.0,
        engine_process_stream_drain_seconds=0.1,
        engine_process_kill_grace_seconds=2.0,
        max_text_length=10_000,
        moss_prompt_audio_path=None,
        moss_apply_angevoice_rules=False,
        moss_mixed_english_policy="preserve",
        moss_default_voice="Junhao",
    )
    client = EngineProcessClient(config=config, spec=EngineWorkerSpec("recording", _recording_factory))
    try:
        metadata = client.load(timeout=15)
        assert metadata["pid"] == client.pid != os.getpid()
        yield client
    finally:
        client.close()
        assert not client.alive


@pytest.mark.parametrize("command", ["synthesize", "synthesize_array", "synthesize_stream"])
def test_prepared_and_raw_requests_cross_real_spawn_without_state_leaks(worker, command):
    pid = worker.pid
    for index, kwargs in enumerate(({}, {"text_prepared": True}, {}, {"text_prepared": False}), 1):
        payload = {"text": TEXT, **kwargs}
        if command == "synthesize_stream":
            events = list(worker.stream(payload, timeout=15))
            assert [event["type"] for event in events] == ["observed", "done"]
            result = {key: value for key, value in events[0].items() if key != "type"}
        else:
            result = worker.request(command, payload, timeout=15)
        assert result == {"text": TEXT, "prepared": kwargs.get("text_prepared", False), "pid": pid, "call": index}
        assert worker.pid == pid
        assert payload == {"text": TEXT, **kwargs}, "transport must not mutate caller-owned input"


@pytest.mark.parametrize("model", ["kokoro", "moss"])
def test_engine_parent_paths_keep_prepared_marker_across_live_worker(worker, model):
    if model == "kokoro":
        parent = KokoroAdapter.__new__(KokoroAdapter)
        parent._cfg = worker.config
        parent._worker = worker
        parent._engine = None
    else:
        parent = MossNanoEngine.__new__(MossNanoEngine)
        parent.config = worker.config
        parent.engine_id = "moss"
        parent._loaded = True
        parent._runtime = None
        parent._process_isolated = True
        parent._process_client = worker
        parent._segment_text = lambda text: [text]

    pid = worker.pid
    for kwargs in ({"text_prepared": True}, {}, {"text_prepared": True}, {"text_prepared": False}):
        result = parent.synthesize_array(text=TEXT, **kwargs)
        assert result["prepared"] is kwargs.get("text_prepared", False)
        assert result["pid"] == pid
        # The MOSS parent retains its raw cleanup; prepared dates/amounts survive.
        if kwargs.get("text_prepared") or model == "kokoro":
            assert result["text"] == TEXT
        events = list(parent.synthesize_stream(text=TEXT, **kwargs))
        assert [event["type"] for event in events] == ["observed", "done"]
        assert events[0]["prepared"] is kwargs.get("text_prepared", False)
        assert events[0]["text"] == result["text"]
        assert events[0]["pid"] == pid
        assert events[0]["call"] == result["call"] + 1
