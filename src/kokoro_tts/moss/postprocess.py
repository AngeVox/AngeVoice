"""Compatibility exports for pure MOSS audio postprocess helpers."""

from __future__ import annotations

from kokoro_tts.moss_runtime.audio import (
    MossAudioQuality,
    amplitude_threshold,
    analyze_silence,
    clamp_pause_seconds,
    compress_long_silence,
    concat_waveforms,
    crossfade_concat,
    ensure_audio_shape,
    normalize_waveform,
    silence_array,
    split_waveform_for_stream,
    trim_silence_edges,
)

__all__ = [
    "MossAudioQuality",
    "amplitude_threshold",
    "analyze_silence",
    "clamp_pause_seconds",
    "compress_long_silence",
    "concat_waveforms",
    "crossfade_concat",
    "ensure_audio_shape",
    "normalize_waveform",
    "silence_array",
    "split_waveform_for_stream",
    "trim_silence_edges",
]
