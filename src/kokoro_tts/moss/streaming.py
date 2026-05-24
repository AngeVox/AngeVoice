"""MOSS 流式解码辅助逻辑。"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class StreamBudgetThresholds:
    """流式解码预算阈值。"""

    low: float = 0.25
    mid: float = 0.65
    high: float = 1.20


def resolve_stream_decode_frame_budget(
    emitted_samples_total: int,
    sample_rate: int,
    first_audio_emitted_at_perf: float | None,
    thresholds: StreamBudgetThresholds | None = None,
) -> int:
    """根据当前播放余量选择一次解码多少帧。"""

    thresholds = thresholds or StreamBudgetThresholds()
    if not first_audio_emitted_at_perf:
        return 1
    lead_seconds = (int(emitted_samples_total) / float(sample_rate or 1)) - max(
        0.0,
        time.perf_counter() - float(first_audio_emitted_at_perf),
    )
    if lead_seconds < thresholds.low:
        return 1
    if lead_seconds < thresholds.mid:
        return 2
    if lead_seconds < thresholds.high:
        return 4
    return 8


def runtime_supports_frame_streaming(runtime) -> bool:
    """判断官方 runtime 是否支持逐帧回调式实时解码。"""

    return (
        runtime is not None
        and hasattr(runtime, "generate_audio_frames")
        and hasattr(runtime, "codec_streaming_session")
        and hasattr(runtime, "encode_text")
        and hasattr(runtime, "build_voice_clone_request_rows")
    )


def merge_codec_audio(audio, audio_length: int, *, channels: int) -> np.ndarray:
    """把官方 codec streaming session 输出整理成 AngeVoice 波形格式。"""

    expected_channels = max(1, int(channels))
    raw = np.asarray(audio, dtype=np.float32)
    if raw.ndim < 3 or int(audio_length) <= 0:
        return np.zeros((0, expected_channels), dtype=np.float32)
    channel_count = int(raw.shape[1])
    channel_arrays = [
        np.asarray(raw[0, channel_index, : int(audio_length)], dtype=np.float32)
        for channel_index in range(channel_count)
    ]
    if not channel_arrays:
        return np.zeros((0, expected_channels), dtype=np.float32)
    merged = np.stack(channel_arrays, axis=1)
    if int(merged.shape[1]) == expected_channels:
        return merged
    if int(merged.shape[1]) > expected_channels:
        return merged[:, :expected_channels]
    return np.repeat(merged[:, :1], expected_channels, axis=1)
