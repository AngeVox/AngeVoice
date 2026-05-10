"""MOSS 音频后处理工具。

目标是把削峰、归一化、静音片段、流式分片等纯逻辑从主引擎中拆出，
便于单独测试，也方便后续继续优化听感。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator

import numpy as np


@dataclass(frozen=True)
class MossAudioQuality:
    """一次波形后处理产生的质量指标。"""

    max_abs_before: float
    scale: float
    max_abs_after: float
    clip_ratio: float

    def as_dict(self) -> dict[str, float]:
        return {
            "max_abs_before": round(self.max_abs_before, 6),
            "scale": round(self.scale, 6),
            "max_abs_after": round(self.max_abs_after, 6),
            "clip_ratio": round(self.clip_ratio, 6),
        }


def normalize_waveform(
    waveform,
    *,
    channels: int,
    gain: float = 1.0,
    target_peak: float = 0.88,
    peak_normalize_enabled: bool = True,
) -> tuple[np.ndarray, MossAudioQuality]:
    """整理 MOSS 输出波形，并用温和峰值保护降低失真风险。"""

    audio = np.asarray(waveform, dtype=np.float32)
    if audio.ndim == 0:
        audio = audio.reshape(1)
    elif audio.ndim > 2:
        audio = audio.reshape(-1, audio.shape[-1])
    if audio.ndim == 1:
        audio = audio.reshape(-1, 1)

    expected_channels = max(1, int(channels))
    if int(audio.shape[1]) != expected_channels:
        if int(audio.shape[1]) > expected_channels:
            audio = audio.mean(axis=1, keepdims=True)
        if expected_channels > int(audio.shape[1]):
            audio = np.repeat(audio[:, :1], expected_channels, axis=1)

    audio = np.nan_to_num(audio, nan=0.0, posinf=0.0, neginf=0.0)
    gain = float(gain)
    if gain != 1.0:
        audio = audio * gain

    max_abs_before = float(np.max(np.abs(audio))) if audio.size else 0.0
    target_peak = float(target_peak)
    scale = 1.0
    if bool(peak_normalize_enabled) and max_abs_before > target_peak > 0:
        scale = target_peak / max_abs_before
        audio = audio * scale

    clipped = np.clip(audio, -1.0, 1.0).astype(np.float32, copy=False)
    clip_ratio = float(np.mean(np.abs(clipped) >= 0.999)) if clipped.size else 0.0
    quality = MossAudioQuality(
        max_abs_before=max_abs_before,
        scale=scale,
        max_abs_after=float(np.max(np.abs(clipped))) if clipped.size else 0.0,
        clip_ratio=clip_ratio,
    )
    return clipped, quality


def split_waveform_for_stream(waveform, *, sample_rate: int, chunk_seconds: float, min_floor: float) -> Iterator[np.ndarray]:
    """按流式输出块大小切分波形。"""

    audio = np.asarray(waveform, dtype=np.float32)
    if audio.size == 0:
        return
    max_seconds = max(float(min_floor), float(chunk_seconds))
    max_samples = max(1, int(int(sample_rate) * max_seconds))
    total_samples = int(audio.shape[0])
    for start in range(0, total_samples, max_samples):
        yield np.ascontiguousarray(audio[start : start + max_samples])


def concat_waveforms(waveforms: Iterable[np.ndarray]) -> np.ndarray:
    """合并非空波形。"""

    parts = [item for item in waveforms if getattr(item, "size", 0)]
    if not parts:
        raise RuntimeError("MOSS: all segments produced empty audio")
    return np.concatenate(parts)


def silence_array(seconds: float, *, sample_rate: int, channels: int) -> np.ndarray:
    """生成指定时长的静音波形。"""

    samples = max(0, int(int(sample_rate) * max(0.0, float(seconds))))
    expected_channels = max(1, int(channels))
    if samples <= 0:
        return np.zeros((0, expected_channels), dtype=np.float32)
    return np.zeros((samples, expected_channels), dtype=np.float32)
