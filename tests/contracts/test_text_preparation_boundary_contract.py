"""Behavior contract for one authoritative request-selected text-normalization pass.

CURRENT GREEN tests preserve direct-call compatibility and unrelated preparation.
FUTURE RED tests define the narrow ``text_prepared`` implementation boundary.  They
are intentionally not xfailed: the freeze artifact records their present failures.
"""

from __future__ import annotations

import concurrent.futures
import inspect
import threading
from contextlib import nullcontext
from types import MethodType, SimpleNamespace

import pytest


_DATE_AMOUNT = "今天是2026-05-20\t价格是123.45元\x00"
_MOSS_MIXED = "今天是2026-05-20，讨论 work-life balance"


def _accepts_keyword(method, name: str) -> bool:
    parameters = inspect.signature(method).parameters.values()
    return any(item.kind == inspect.Parameter.VAR_KEYWORD or item.name == name for item in parameters)


def _invoke_with_prepared(method, *args, **kwargs):
    """Exercise today's callable and the future optional marker without TypeError noise."""

    if _accepts_keyword(method, "text_prepared"):
        kwargs["text_prepared"] = True
    return method(*args, **kwargs)


def _kokoro_engine():
    from kokoro_tts.engine import TTSEngine

    engine = TTSEngine.__new__(TTSEngine)
    engine._loaded = True
    engine.config = SimpleNamespace(max_text_length=10_000, request_timeout_seconds=2.0)
    engine._runtime_lock = threading.RLock()
    engine._do_synthesize = lambda text, _voice, _speed: text
    return engine


class _RecordingRuntime:
    def __init__(self):
        self.prepare_calls: list[dict[str, object]] = []
        self.split_calls: list[tuple[str, int]] = []

    def prepare_synthesis_text(self, **kwargs):
        self.prepare_calls.append(dict(kwargs))
        return {"text": kwargs["text"]}

    def split_voice_clone_text(self, text: str, max_tokens: int):
        self.split_calls.append((text, max_tokens))
        return [text]

    def synthesize_single_chunk(self, **_kwargs):
        return {"waveform": [0.0]}


def _moss_runtime_engine(*, wetext: bool, robust: bool, apply_rules=False):
    from kokoro_tts.moss_engine import MossNanoEngine

    runtime = _RecordingRuntime()
    engine = MossNanoEngine.__new__(MossNanoEngine)
    engine.config = SimpleNamespace(
        max_text_length=10_000,
        request_timeout_seconds=2.0,
        moss_prompt_audio_path=None,
        moss_apply_angevoice_rules=apply_rules,
        moss_mixed_english_policy="translate",
        moss_enable_wetext_processing=wetext,
        moss_enable_normalize_tts_text=robust,
        moss_realtime_streaming_decode=False,
        moss_audio_polish_enabled=False,
        moss_default_voice="Junhao",
    )
    engine.engine_id = "moss"
    engine._loaded = True
    engine._process_isolated = False
    engine._runtime = runtime
    engine._runtime_lock = threading.RLock()
    engine._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    engine._segment_text = MethodType(lambda _self, text, **_kwargs: [text], engine)
    engine._resolve_prompt_audio_codes_cached = lambda **_kwargs: []
    engine._configure_runtime_generation = lambda: None
    engine._effective_text_tokens = lambda: 75
    engine._should_use_incremental_codec = lambda: False
    engine._runtime_supports_frame_streaming = lambda: False
    engine._postprocess_waveform = lambda waveform, **_kwargs: waveform
    engine._concat_waveforms = lambda waveforms: waveforms[0]
    return engine, runtime


class _RecordingWorker:
    is_loaded = True
    is_healthy = True
    alive = True
    pid = 123
    last_exit_reason = ""

    def __init__(self):
        self.requests: list[tuple[str, dict[str, object]]] = []
        self.streams: list[dict[str, object]] = []

    def request(self, command, payload, *, timeout):
        self.requests.append((command, dict(payload)))
        return b"result"

    def stream(self, payload, *, timeout, cancel_check=None):
        self.streams.append(dict(payload))
        yield {"type": "done", "total_segments": 0, "total_audio_chunks": 0}


def _kokoro_isolated_adapter():
    from kokoro_tts.engines.adapters.kokoro import KokoroAdapter

    worker = _RecordingWorker()
    adapter = KokoroAdapter.__new__(KokoroAdapter)
    adapter._cfg = SimpleNamespace(request_timeout_seconds=2.0)
    adapter._process_isolated = True
    adapter._worker = worker
    adapter._engine = None
    return adapter, worker


def _moss_isolated_engine():
    from kokoro_tts.moss_engine import MossNanoEngine

    worker = _RecordingWorker()
    engine = MossNanoEngine.__new__(MossNanoEngine)
    engine.config = SimpleNamespace(
        max_text_length=10_000,
        request_timeout_seconds=2.0,
        engine_process_stream_idle_timeout_seconds=2.0,
        moss_prompt_audio_path=None,
        moss_apply_angevoice_rules=False,
        moss_mixed_english_policy="translate",
        moss_default_voice="Junhao",
    )
    engine.engine_id = "moss"
    engine._loaded = True
    engine._runtime = None
    engine._process_isolated = True
    engine._process_client = worker
    engine._segment_text = MethodType(lambda _self, text, **_kwargs: [text], engine)
    return engine, worker


class _Condition:
    prompt_audio_path = None
    prompt_text = ""


class _Generation:
    @staticmethod
    def as_dict():
        return {}


class _Borrow:
    def __init__(self, engine):
        self.engine = engine

    def __enter__(self):
        return self.engine

    def __exit__(self, *_args):
        return False


class _StreamingCaptureEngine:
    def __init__(self):
        self.kwargs = None

    def synthesize_stream(self, text, voice, speed, fmt, **kwargs):
        self.kwargs = dict(kwargs)
        yield {"type": "done"}


def _streaming_service(engine):
    from kokoro_tts.services.streaming_service import StreamingService

    state = SimpleNamespace(model_manager=SimpleNamespace(borrow=lambda _model: _Borrow(engine)))
    service = StreamingService.__new__(StreamingService)
    service.state = state
    service.cfg = SimpleNamespace()
    return service


def _stream_request(model_id: str):
    return SimpleNamespace(
        model_id=model_id,
        generation=_Generation(),
        condition=_Condition(),
        request_id="contract",
        text="service prepared text",
        voice="voice",
        speed=1.0,
        audio_format="pcm_s16le",
    )


def test_current_green_public_clients_cannot_set_internal_prepared_marker():
    from kokoro_tts.services.streaming_service import StreamingService
    from kokoro_tts.services.synthesis_service import SynthesisService

    assert "text_prepared" not in inspect.signature(SynthesisService.build_request).parameters
    assert "text_prepared" not in inspect.signature(StreamingService.build_request).parameters


def test_current_green_kokoro_direct_raw_keeps_generic_tn_and_safety_cleanup():
    engine = _kokoro_engine()
    result = engine.synthesize_array(_DATE_AMOUNT, "voice", 1.0)

    assert "2026-05-20" not in result
    assert "123.45" not in result
    assert "二零二六年五月二十日" in result
    assert "一百二十三元四角五分" in result
    assert "\x00" not in result and "\t" not in result


def test_current_green_moss_direct_raw_keeps_rule_modes_and_mixed_english_policy():
    from kokoro_tts.moss.text import clean_text

    full = clean_text(_MOSS_MIXED, apply_angevoice_rules=True, mixed_english_policy="translate", model="moss")
    gentle = clean_text(_MOSS_MIXED, apply_angevoice_rules=False, mixed_english_policy="translate", model="moss")
    automatic = clean_text(_MOSS_MIXED, apply_angevoice_rules="auto", mixed_english_policy="translate", model="moss")

    assert "二零二六年五月二十日" in full
    assert "work-life balance" in full
    assert "2026-05-20" in gentle and "工作生活平衡" in gentle
    assert automatic == gentle


def test_current_green_moss_direct_raw_preserves_runtime_flags_validation_and_chunking():
    for wetext, robust in ((False, False), (False, True), (True, False), (True, True)):
        engine, runtime = _moss_runtime_engine(wetext=wetext, robust=robust)
        try:
            engine.synthesize_array("direct raw text", "Junhao", 1.0)
            assert runtime.prepare_calls[-1]["enable_wetext"] is wetext
            assert runtime.prepare_calls[-1]["enable_normalize_tts_text"] is robust
            assert runtime.split_calls == [("direct raw text", 75)]
            with pytest.raises(ValueError, match="文本不能为空"):
                _invoke_with_prepared(engine.synthesize_array, "", "Junhao", 1.0)
        finally:
            engine._executor.shutdown(wait=True)


def test_current_green_zipvoice_prepared_boundary_remains_unchanged():
    from kokoro_tts.zipvoice.engine import ZipVoiceEngine

    worker = _RecordingWorker()
    engine = ZipVoiceEngine.__new__(ZipVoiceEngine)
    engine.cfg = SimpleNamespace(request_timeout_seconds=2.0, max_text_length=10_000)
    engine.public_id = "zipvoice"
    engine._worker = worker
    engine._state_lock = nullcontext()

    engine.synthesize(
        "service prepared text",
        "voice",
        1.0,
        prompt_audio_path="reference.wav",
        prompt_text="prepared prompt",
        text_prepared=True,
        prompt_text_prepared=True,
    )

    payload = worker.requests[-1][1]
    assert payload["text_prepared"] is True
    assert payload["prompt_text_prepared"] is True


@pytest.mark.parametrize("model_id", ["kokoro", "moss"])
def test_future_red_synthesis_service_propagates_prepared_to_generic_tn_engines(model_id):
    from kokoro_tts.services.synthesis_service import SynthesisService

    class Engine:
        def synthesize(self, **_kwargs):
            return b""

    request = SimpleNamespace(model_id=model_id, engine_params={}, condition=_Condition())
    service = SynthesisService.__new__(SynthesisService)

    kwargs = service._inference_kwargs(Engine(), request, "synthesize")
    assert kwargs.get("text_prepared") is True, "service-prepared text lost its internal ownership marker"


@pytest.mark.parametrize("model_id", ["kokoro", "moss"])
def test_future_red_streaming_service_propagates_prepared_to_generic_tn_engines(model_id):
    engine = _StreamingCaptureEngine()
    frames = list(_streaming_service(engine).iter_frames(_stream_request(model_id)))

    assert frames[-1]["type"] == "done"
    assert engine.kwargs.get("text_prepared") is True, "streaming service lost its internal ownership marker"


def test_future_red_kokoro_prepared_skips_generic_tn_but_keeps_safety_cleanup():
    engine = _kokoro_engine()
    result = _invoke_with_prepared(engine.synthesize_array, _DATE_AMOUNT, "voice", 1.0)

    assert result == "今天是2026-05-20 价格是123.45元", (
        "prepared Kokoro text must keep only control-character and whitespace sanitation"
    )


def test_future_red_kokoro_isolated_payload_receives_prepared_marker():
    adapter, worker = _kokoro_isolated_adapter()
    _invoke_with_prepared(adapter.synthesize, "service prepared text", "voice", 1.0)

    assert worker.requests[-1][1].get("text_prepared") is True, "Kokoro child did not receive prepared ownership"


def test_future_red_moss_prepared_bypasses_generic_tn_and_keeps_model_local_english():
    engine, runtime = _moss_runtime_engine(wetext=False, robust=True, apply_rules=True)
    try:
        _invoke_with_prepared(engine.synthesize_array, _MOSS_MIXED, "Junhao", 1.0)
    finally:
        engine._executor.shutdown(wait=True)

    runtime_text = runtime.prepare_calls[-1]["text"]
    assert runtime_text == "今天是2026-05-20，讨论 工作生活平衡", (
        "prepared MOSS text must bypass generic legacy/family rules while retaining its model-local English policy"
    )


@pytest.mark.parametrize("robust", [False, True])
def test_future_red_moss_prepared_disables_runtime_wetext_and_preserves_robust_config(robust):
    engine, runtime = _moss_runtime_engine(wetext=True, robust=robust)
    try:
        _invoke_with_prepared(engine.synthesize_array, "service prepared text", "Junhao", 1.0)
    finally:
        engine._executor.shutdown(wait=True)

    call = runtime.prepare_calls[-1]
    assert call["enable_wetext"] is False, "request-selected TN must not be followed by independent runtime WeText"
    assert call["enable_normalize_tts_text"] is robust, "pinned robust format sanitation remains config-owned"
    assert runtime.split_calls == [("service prepared text", 75)], "prepared ownership must not bypass chunking"


def test_future_red_moss_isolated_stream_and_nonstream_payloads_keep_prepared_marker():
    engine, worker = _moss_isolated_engine()

    _invoke_with_prepared(engine.synthesize_array, "service prepared text", "Junhao", 1.0)
    list(_invoke_with_prepared(engine.synthesize_stream, "service prepared text", "Junhao", 1.0, "pcm_s16le"))

    payloads = [worker.requests[-1][1], worker.streams[-1]]
    assert [payload.get("text_prepared") for payload in payloads] == [True, True], (
        "MOSS isolated nonstream/stream commands must share prepared ownership policy"
    )
