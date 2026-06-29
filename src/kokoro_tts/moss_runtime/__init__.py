"""Lightweight MOSS runtime helper facade.

This package exposes pure helpers only. It must stay free of ONNX session, model
discovery, codec invocation and process lifecycle side effects.
"""

from __future__ import annotations

from .audio import (
    MossAudioQuality,
    analyze_silence,
    clamp_pause_seconds,
    compress_long_silence,
    concat_waveforms,
    normalize_waveform,
    silence_array,
    split_waveform_for_stream,
    trim_silence_edges,
)
from .prompt import prompt_audio_cache_key
from .streaming import (
    StreamBudgetThresholds,
    merge_codec_audio,
    resolve_stream_decode_frame_budget,
    runtime_supports_frame_streaming,
)

__all__ = [
    "MossAudioQuality",
    "StreamBudgetThresholds",
    "analyze_silence",
    "clamp_pause_seconds",
    "compress_long_silence",
    "concat_waveforms",
    "merge_codec_audio",
    "normalize_waveform",
    "prompt_audio_cache_key",
    "resolve_stream_decode_frame_budget",
    "runtime_supports_frame_streaming",
    "silence_array",
    "split_waveform_for_stream",
    "trim_silence_edges",
]
