from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np

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
    monkeypatch.setattr("kokoro_tts.moss.streaming.time.perf_counter", lambda: 100.0)
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
