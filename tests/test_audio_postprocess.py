import numpy as np

from kokoro_tts.moss.postprocess import (
    clamp_pause_seconds,
    compress_long_silence,
    concat_waveforms,
    trim_silence_edges,
)


def test_compress_long_silence_stereo():
    sr = 1000
    tone = np.ones((100, 2), dtype=np.float32) * 0.2
    silence = np.zeros((2500, 2), dtype=np.float32)
    audio = np.concatenate([tone, silence, tone], axis=0)
    compressed, metrics = compress_long_silence(
        audio,
        sample_rate=sr,
        channels=2,
        threshold_db=-45,
        max_silence_ms=900,
    )
    assert compressed.shape[1] == 2
    assert compressed.shape[0] <= 100 + 900 + 100
    assert metrics["long_silence_count"] == 1
    assert metrics["max_silence_ms"] >= 2400


def test_crossfade_concat_keeps_stereo_shape():
    a = np.ones((100, 2), dtype=np.float32) * 0.2
    b = np.ones((100, 2), dtype=np.float32) * -0.2
    merged = concat_waveforms([a, b], crossfade_ms=20, sample_rate=1000, channels=2)
    assert merged.shape == (180, 2)
    assert np.max(np.abs(merged)) <= 0.21


def test_trim_silence_edges_reports_trimmed_ms():
    sr = 1000
    silence = np.zeros((100, 2), dtype=np.float32)
    tone = np.ones((200, 2), dtype=np.float32) * 0.2
    audio = np.concatenate([silence, tone, silence], axis=0)
    trimmed, start_ms, end_ms = trim_silence_edges(audio, sample_rate=sr, channels=2, threshold_db=-45, keep_ms=10)
    assert trimmed.shape[1] == 2
    assert trimmed.shape[0] == 220
    assert 80 <= start_ms <= 100
    assert 80 <= end_ms <= 100


def test_clamp_pause_seconds():
    assert clamp_pause_seconds(5.0, max_ms=650) == 0.65
    assert clamp_pause_seconds(-1.0, max_ms=650) == 0.0
