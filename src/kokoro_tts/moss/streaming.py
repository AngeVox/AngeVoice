"""Compatibility exports for pure MOSS streaming helpers."""

from __future__ import annotations

from kokoro_tts.moss_runtime.streaming import (
    StreamBudgetThresholds,
    merge_codec_audio,
    resolve_stream_decode_frame_budget,
    runtime_supports_frame_streaming,
)

__all__ = [
    "StreamBudgetThresholds",
    "merge_codec_audio",
    "resolve_stream_decode_frame_budget",
    "runtime_supports_frame_streaming",
]
