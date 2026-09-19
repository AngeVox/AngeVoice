from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import threading
from concurrent.futures import ThreadPoolExecutor

from kokoro_tts.moss.postprocess import ensure_audio_shape, normalize_waveform, split_waveform_for_stream
from kokoro_tts.moss.prompt import prompt_audio_cache_key
from kokoro_tts.moss.streaming import (
    StreamBudgetThresholds,
    merge_codec_audio,
    resolve_stream_decode_frame_budget,
    runtime_supports_frame_streaming,
)
from kokoro_tts.moss_runtime import prompt_audio_cache_key as runtime_prompt_audio_cache_key
from kokoro_tts.moss_runtime.audio import normalize_waveform as runtime_normalize_waveform
from kokoro_tts.moss_runtime.streaming import (
    merge_codec_audio as runtime_merge_codec_audio,
    resolve_stream_decode_frame_budget as runtime_resolve_stream_decode_frame_budget,
)


def test_cancelled_moss_worker_waiting_for_runtime_lock_skips_prompt(monkeypatch):
    from kokoro_tts.config import TTSConfig
    from kokoro_tts.moss_engine import MossNanoEngine

    engine = MossNanoEngine(TTSConfig(), process_isolation=False)
    cancelled = threading.Event()
    waiting = threading.Event()
    gate = threading.Lock()
    gate.acquire()
    calls = []

    class ObservedLock:
        def __enter__(self):
            waiting.set()
            gate.acquire()

        def __exit__(self, *args):
            gate.release()

    monkeypatch.setattr(engine, "_runtime_lock", ObservedLock())
    monkeypatch.setattr(engine, "_validate_request", lambda **kw: None)
    monkeypatch.setattr(engine, "_clean_text", lambda text, **kw: text)
    monkeypatch.setattr(engine, "_segment_text", lambda text: [text])
    monkeypatch.setattr(engine, "_resolve_prompt_audio_codes_cached", lambda **kw: calls.append("prompt") or [])
    monkeypatch.setattr(engine, "_configure_runtime_generation", lambda: calls.append("configure"))
    consumer = ThreadPoolExecutor(max_workers=1)
    try:
        result = consumer.submit(lambda: list(engine.synthesize_stream("hello", cancel_check=cancelled.is_set)))
        assert waiting.wait(3)
        cancelled.set()
        frames = result.result(timeout=3)
        assert [frame["type"] for frame in frames] == ["started", "done"]
    finally:
        cancelled.set()
        gate.release()
        consumer.shutdown(wait=True)
        engine._executor.shutdown(wait=True)
    assert calls == []


def test_cancel_during_prompt_preparation_skips_generation_configuration(monkeypatch):
    from kokoro_tts.config import TTSConfig
    from kokoro_tts.moss_engine import MossNanoEngine
    from kokoro_tts.moss_engine_streaming import _MossStreamCancelled

    engine = MossNanoEngine(TTSConfig(), process_isolation=False)
    cancelled = threading.Event()
    calls = []

    def prompt(**kwargs):
        cancelled.set()
        return []

    monkeypatch.setattr(engine, "_resolve_prompt_audio_codes_cached", prompt)
    monkeypatch.setattr(engine, "_configure_runtime_generation", lambda: calls.append("configure"))
    try:
        with pytest.raises(_MossStreamCancelled):
            engine._push_stream_waveforms(segments=["hello"], put_item=lambda item: True,
                                         is_cancelled=cancelled.is_set)
        assert calls == []
        cancelled.clear()
        monkeypatch.setattr(engine, "_resolve_prompt_audio_codes_cached", lambda **kw: [])
        monkeypatch.setattr(engine, "_stream_runtime_chunks", lambda *a, **kw: calls.append("decode") or 0)
        engine._push_stream_waveforms(segments=["hello"], put_item=lambda item: True,
                                     is_cancelled=cancelled.is_set)
        assert calls == ["configure", "decode"]
    finally:
        engine._executor.shutdown(wait=True)


def test_moss_closed_consumer_does_not_release_active_producer_lock(monkeypatch):
    from kokoro_tts.config import TTSConfig
    from kokoro_tts.moss_engine import MossNanoEngine
    import kokoro_tts.moss_engine_streaming as module

    engine = MossNanoEngine(TTSConfig(), process_isolation=False)
    release = threading.Event()
    cleaned = threading.Event()
    observed = []

    def produce(**kwargs):
        try:
            assert kwargs["put_item"](("audio", np.zeros((1, 1))))
            observed.append((release.wait(3), kwargs["is_cancelled"]()))
        finally:
            cleaned.set()

    monkeypatch.setattr(engine, "_validate_request", lambda **kw: None)
    monkeypatch.setattr(engine, "_clean_text", lambda text, **kw: text)
    monkeypatch.setattr(engine, "_segment_text", lambda text: [text])
    monkeypatch.setattr(engine, "_push_stream_waveforms", produce)
    monkeypatch.setattr(module, "encode_audio_segment", lambda *args: b"audio")
    stream = engine.synthesize_stream("hello")
    try:
        assert next(stream)["type"] == "started"
        assert next(stream)["type"] == "audio"
        stream.close()
        assert not cleaned.is_set()
        acquired = engine._runtime_lock.acquire(blocking=False)
        if acquired:
            engine._runtime_lock.release()
        assert not acquired
    finally:
        stream.close()
        release.set()
        engine._executor.shutdown(wait=True)
    assert cleaned.is_set()
    assert observed == [(True, True)]
    assert engine._runtime_lock.acquire(blocking=False)
    engine._runtime_lock.release()


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("failure", ["oom", "cancel", "interrupt", "success", "entry"])
def test_codec_reset_preserves_primary_failure_and_resets_next_request(monkeypatch, streaming, failure):
    from kokoro_tts.config import TTSConfig
    from kokoro_tts.moss_engine import MossNanoEngine
    from kokoro_tts.moss_engine_streaming import _MossStreamCancelled

    engine = MossNanoEngine(TTSConfig(), process_isolation=False)
    primary = {"oom": RuntimeError("CUDA out of memory"), "cancel": _MossStreamCancelled(),
               "interrupt": KeyboardInterrupt()}.get(failure)
    cleanup = RuntimeError("codec reset failed")
    state = SimpleNamespace(resets=0, generated=0, fail_reset=True)

    def reset():
        state.resets += 1
        if state.fail_reset and state.resets == (1 if failure == "entry" else 2):
            raise cleanup

    def generate(rows, *, on_frame):
        state.generated += 1
        if primary is not None:
            raise primary
        on_frame([], 0, [1])
        return [[1]]

    engine._runtime = SimpleNamespace(
        codec_meta={"codec_config": {"channels": 1, "sample_rate": 24000}},
        codec_streaming_session=SimpleNamespace(reset=reset, run_frames=lambda frames: (np.zeros((1, 1)), 1)),
        encode_text=lambda text: [1], build_voice_clone_request_rows=lambda *args: [],
        generate_audio_frames=generate,
    )
    monkeypatch.setattr(engine, "_runtime_supports_frame_streaming", lambda: True)
    monkeypatch.setattr(engine, "_prepare_runtime_text_chunks", lambda *a, **kw: ["hello"])
    monkeypatch.setattr(engine, "_merge_codec_audio", lambda audio, length: audio)
    monkeypatch.setattr(engine, "_emit_stream_waveform", lambda *a, **kw: 1)

    def invoke():
        if streaming:
            return engine._stream_runtime_chunks("hello", prompt_audio_codes=[], put_item=lambda item: True,
                is_cancelled=lambda: False,
                stream_state={"emitted_samples_total": 0, "first_audio_emitted_at_perf": None})
        return engine._synthesize_single_chunk_incremental("hello", [])

    try:
        expected = primary if primary is not None else cleanup
        with pytest.raises(type(expected)) as caught:
            invoke()
        assert caught.value is expected
        assert state.resets == (1 if failure == "entry" else 2)
        assert state.generated == (0 if failure == "entry" else 1)
        primary = None
        state.fail_reset = False
        before = state.resets
        invoke()
        assert state.resets == before + 2
    finally:
        engine._executor.shutdown(wait=True)


@pytest.fixture
def vram_engine(monkeypatch, tmp_path):
    from kokoro_tts import moss_engine as module
    from kokoro_tts.config import TTSConfig

    clock = [0.0]
    snapshots, calls = [], []
    def probe():
        calls.append(clock[0])
        return snapshots.pop(0)
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(module, "get_cuda_vram_snapshot", probe)
    engine = module.MossNanoEngine(
        TTSConfig(model_dir=tmp_path, moss_vram_snapshot_ttl_seconds=60,
                  moss_segment_length=400, moss_max_new_frames=500,
                  moss_voice_clone_max_text_tokens=128, moss_low_vram_segment_length=160,
                  moss_low_vram_max_new_frames=300, moss_low_vram_text_tokens=56),
        execution_provider="cuda", process_isolation=False,
    )
    try:
        yield engine, clock, snapshots, calls
    finally:
        engine._executor.shutdown(wait=True)


def test_vram_first_failed_probe_obeys_ttl_without_a_successful_snapshot(vram_engine):
    from kokoro_tts.moss.vram import VramSnapshot

    engine, clock, snapshots, calls = vram_engine
    snapshots.extend([VramSnapshot(False), VramSnapshot(True, free_mb=2000)])
    engine._refresh_vram_guard()
    clock[0] = 1
    engine._refresh_vram_guard()
    assert calls == [0]
    assert engine._vram_status()["available"] is False
    clock[0] = 60
    engine._refresh_vram_guard()
    assert calls == [0, 60]
    assert engine._vram_status()["free_mb"] == 2000


def test_vram_oom_without_prior_snapshot_keeps_conservative_limits_until_ttl(vram_engine):
    from kokoro_tts.moss.vram import VramSnapshot

    engine, clock, snapshots, calls = vram_engine
    snapshots.append(VramSnapshot(True, free_mb=2000))
    engine._record_full_decode_oom(RuntimeError("synthetic allocation failure"))
    assert engine._effective_segment_length() == 160
    assert engine._effective_max_new_frames() == 300
    assert engine._effective_text_tokens() == 56
    assert calls == []
    clock[0] = 60
    assert engine._effective_segment_length() == 400
    assert calls == [60]
    # The longer full-codec cooldown is independent of the refreshed limits.
    assert engine._should_use_incremental_codec() is True


def test_vram_failed_refresh_retains_last_good_snapshot_and_low_mode(vram_engine):
    from kokoro_tts.moss.vram import VramSnapshot

    engine, clock, snapshots, calls = vram_engine
    snapshots.extend([VramSnapshot(True, free_mb=700), VramSnapshot(False)])
    engine._refresh_vram_guard()
    clock[0] = 60
    engine._refresh_vram_guard()
    clock[0] = 61
    assert engine._effective_max_new_frames() == 300
    assert engine._vram_status()["free_mb"] == 700
    assert calls == [0, 60]


@pytest.mark.parametrize("force,ttl", [(True, 60), (False, 0), (False, -1)])
def test_vram_force_and_disabled_ttl_allow_immediate_retry(vram_engine, force, ttl):
    from kokoro_tts.moss.vram import VramSnapshot

    engine, clock, snapshots, calls = vram_engine
    engine.config.moss_vram_snapshot_ttl_seconds = ttl
    snapshots.extend([VramSnapshot(False), VramSnapshot(True, free_mb=2000)])
    engine._refresh_vram_guard()
    engine._refresh_vram_guard(force=force)
    assert calls == [0, 0]
    assert engine._vram_status()["free_mb"] == 2000


@pytest.mark.parametrize("free,low,critical", [(599, True, True), (600, True, False), (1199, True, False), (1200, False, False)])
def test_vram_threshold_boundaries_preserve_low_mode_and_codec_cooldown(vram_engine, free, low, critical):
    from kokoro_tts.moss.vram import VramSnapshot

    engine, clock, snapshots, calls = vram_engine
    snapshots.append(VramSnapshot(True, free_mb=free))
    engine._refresh_vram_guard()
    assert engine._low_vram_mode is low
    assert (engine._full_decode_disabled_until > 0) is critical


@pytest.mark.parametrize("provider,enabled", [("cpu", True), ("cuda", False)])
def test_vram_inactive_guard_never_probes_and_clears_low_mode(vram_engine, provider, enabled):
    engine, clock, snapshots, calls = vram_engine
    engine.execution_provider = provider
    engine.config.moss_vram_guard_enabled = enabled
    engine._low_vram_mode = True
    engine._refresh_vram_guard(force=True)
    assert calls == []
    assert engine._low_vram_mode is False


def test_vram_unload_resets_probe_schedule(vram_engine, monkeypatch):
    from kokoro_tts.moss.vram import VramSnapshot
    import torch

    engine, clock, snapshots, calls = vram_engine
    snapshots.extend([VramSnapshot(False), VramSnapshot(True, free_mb=2000)])
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    engine._refresh_vram_guard()
    engine.unload()
    engine._refresh_vram_guard()
    assert calls == [0, 0]
    assert engine._vram_status()["free_mb"] == 2000


def test_2615_moss_prompt_cache_key_contract_for_voice_and_prompt_file(tmp_path):
    prompt = tmp_path / "prompt.wav"
    prompt.write_bytes(b"prompt-audio")

    assert prompt_audio_cache_key(
        voice="",
        default_voice="Junhao",
        prompt_audio_path=None,
        max_seconds=8,
        sample_rate=48000,
        channels=2,
    ) == "voice:Junhao"

    key = prompt_audio_cache_key(
        voice="Custom",
        default_voice="Junhao",
        prompt_audio_path=str(prompt),
        max_seconds=8,
        sample_rate=48000,
        channels=2,
    )
    assert key.startswith("prompt:")
    assert ":voice:Custom:maxsec:8.000:sr:48000:ch:2" in key
    assert key == prompt_audio_cache_key(
        voice="Custom",
        default_voice="Junhao",
        prompt_audio_path=str(prompt),
        max_seconds=8,
        sample_rate=48000,
        channels=2,
    )


def test_2615_moss_stream_budget_and_runtime_capability_contract(monkeypatch):
    monkeypatch.setattr("kokoro_tts.moss_runtime.streaming.time.perf_counter", lambda: 100.0)
    thresholds = StreamBudgetThresholds(low=0.25, mid=0.65, high=1.20)

    assert resolve_stream_decode_frame_budget(0, 24000, None, thresholds) == 1
    assert resolve_stream_decode_frame_budget(2400, 24000, 99.95, thresholds) == 1
    assert resolve_stream_decode_frame_budget(12000, 24000, 99.90, thresholds) == 2
    assert resolve_stream_decode_frame_budget(24000, 24000, 99.90, thresholds) == 4
    assert resolve_stream_decode_frame_budget(48000, 24000, 99.90, thresholds) == 8

    capable = SimpleNamespace(
        generate_audio_frames=lambda: None,
        codec_streaming_session=lambda: None,
        encode_text=lambda: None,
        build_voice_clone_request_rows=lambda: None,
    )
    assert runtime_supports_frame_streaming(capable) is True
    assert runtime_supports_frame_streaming(SimpleNamespace(generate_audio_frames=lambda: None)) is False


def test_2615_moss_audio_postprocess_shape_normalize_and_stream_chunks():
    mono = ensure_audio_shape(np.array([0.0, 0.5, -0.5], dtype=np.float32), channels=2)
    assert mono.shape == (3, 2)
    assert np.allclose(mono[:, 0], mono[:, 1])

    clipped, quality = normalize_waveform(np.array([[0.0], [2.0], [-2.0]], dtype=np.float32), channels=1, target_peak=0.8)
    assert clipped.shape == (3, 1)
    assert float(np.max(np.abs(clipped))) <= 1.0
    assert quality.as_dict()["scale"] <= 1.0

    chunks = list(split_waveform_for_stream(np.arange(10, dtype=np.float32).reshape(10, 1), sample_rate=10, chunk_seconds=0.3, min_floor=0.2))
    assert [chunk.shape[0] for chunk in chunks] == [3, 3, 3, 1]


def test_2615_moss_streaming_codec_audio_merge_contract():
    raw = np.array([[[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]], dtype=np.float32)

    stereo = merge_codec_audio(raw, 2, channels=2)
    assert stereo.tolist() == [[1.0, 4.0], [2.0, 5.0]]

    mono = merge_codec_audio(raw, 2, channels=1)
    assert mono.tolist() == [[1.0], [2.0]]

    expanded = merge_codec_audio(np.array([[[1.0, 2.0, 3.0]]], dtype=np.float32), 2, channels=2)
    assert expanded.tolist() == [[1.0, 1.0], [2.0, 2.0]]


def test_2615_moss_runtime_facade_stays_pure_and_equivalent(tmp_path):
    import sys

    forbidden_imports = [
        "onnx_tts_runtime",
        "ort_cpu_runtime",
        "kokoro_tts.service_state",
        "kokoro_tts.routes.ws",
        "kokoro_tts.routes.status",
        "kokoro_tts.admin_config_schema",
    ]
    before = {name for name in forbidden_imports if name in sys.modules}

    import kokoro_tts.moss_runtime.audio  # noqa: F401
    import kokoro_tts.moss_runtime.prompt  # noqa: F401
    import kokoro_tts.moss_runtime.streaming  # noqa: F401

    after = {name for name in forbidden_imports if name in sys.modules}
    assert after == before

    prompt = tmp_path / "prompt.wav"
    prompt.write_bytes(b"prompt-audio")
    assert runtime_prompt_audio_cache_key(
        voice="Custom",
        default_voice="Junhao",
        prompt_audio_path=str(prompt),
        max_seconds=8,
        sample_rate=48000,
        channels=2,
    ) == prompt_audio_cache_key(
        voice="Custom",
        default_voice="Junhao",
        prompt_audio_path=str(prompt),
        max_seconds=8,
        sample_rate=48000,
        channels=2,
    )

    assert runtime_resolve_stream_decode_frame_budget(0, 24000, None) == resolve_stream_decode_frame_budget(0, 24000, None)
    raw = np.array([[[1.0, 2.0], [3.0, 4.0]]], dtype=np.float32)
    assert np.array_equal(runtime_merge_codec_audio(raw, 2, channels=2), merge_codec_audio(raw, 2, channels=2))

    waveform = np.array([[0.0], [2.0], [-2.0]], dtype=np.float32)
    expected, expected_quality = normalize_waveform(waveform, channels=1, target_peak=0.8)
    actual, actual_quality = runtime_normalize_waveform(waveform, channels=1, target_peak=0.8)
    assert np.array_equal(actual, expected)
    assert actual_quality.as_dict() == expected_quality.as_dict()


def test_2615_moss_legacy_helpers_reexport_runtime_sources():
    import kokoro_tts.moss.postprocess as legacy_postprocess
    import kokoro_tts.moss.prompt as legacy_prompt
    import kokoro_tts.moss.streaming as legacy_streaming
    import kokoro_tts.moss_runtime.audio as runtime_audio
    import kokoro_tts.moss_runtime.prompt as runtime_prompt
    import kokoro_tts.moss_runtime.streaming as runtime_streaming

    assert legacy_postprocess.MossAudioQuality is runtime_audio.MossAudioQuality
    assert legacy_postprocess.ensure_audio_shape is runtime_audio.ensure_audio_shape
    assert legacy_postprocess.normalize_waveform is runtime_audio.normalize_waveform
    assert legacy_postprocess.split_waveform_for_stream is runtime_audio.split_waveform_for_stream
    assert legacy_prompt.prompt_audio_cache_key is runtime_prompt.prompt_audio_cache_key
    assert legacy_streaming.StreamBudgetThresholds is runtime_streaming.StreamBudgetThresholds
    assert legacy_streaming.merge_codec_audio is runtime_streaming.merge_codec_audio
    assert legacy_streaming.resolve_stream_decode_frame_budget is runtime_streaming.resolve_stream_decode_frame_budget
