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
    repaired_impulses: int = 0
    dc_offset_before: float = 0.0
    long_silence_count: int = 0
    max_silence_ms: float = 0.0
    silence_ratio: float = 0.0
    trimmed_start_ms: float = 0.0
    trimmed_end_ms: float = 0.0

    def as_dict(self) -> dict[str, float]:
        return {
            "max_abs_before": round(self.max_abs_before, 6),
            "scale": round(self.scale, 6),
            "max_abs_after": round(self.max_abs_after, 6),
            "clip_ratio": round(self.clip_ratio, 6),
            "repaired_impulses": float(self.repaired_impulses),
            "dc_offset_before": round(self.dc_offset_before, 6),
            "long_silence_count": float(self.long_silence_count),
            "max_silence_ms": round(self.max_silence_ms, 3),
            "silence_ratio": round(self.silence_ratio, 6),
            "trimmed_start_ms": round(self.trimmed_start_ms, 3),
            "trimmed_end_ms": round(self.trimmed_end_ms, 3),
        }


def normalize_waveform(
    waveform,
    *,
    channels: int,
    gain: float = 1.0,
    target_peak: float = 0.86,
    peak_normalize_enabled: bool = True,
    declick_enabled: bool = True,
    edge_fade_samples: int = 0,
) -> tuple[np.ndarray, MossAudioQuality]:
    """整理 MOSS 输出波形，并用温和峰值/去爆音保护降低失真风险。

    OpenMOSS 在部分参考音频、CUDA/ONNX 组合和小句子流式合成时，偶尔会
    出现很窄的瞬态尖峰或片段边缘不连续。它们不一定达到数字削波，听感上
    却会表现为“噗”“刺”“电流音”。这里做三件保守处理：

    1. 去除极小 DC offset；
    2. 只修复明显孤立的单点/双点脉冲，不改变正常声波主体；
    3. 对片段头尾做短淡入淡出，减少拼接爆音。
    """

    audio = ensure_audio_shape(waveform, channels=channels)
    dc_offset_before = float(np.mean(audio)) if audio.size else 0.0
    if audio.size:
        audio = audio - np.mean(audio, axis=0, keepdims=True).astype(np.float32)

    gain = float(gain)
    if gain != 1.0:
        audio = audio * gain

    repaired_impulses = 0
    if bool(declick_enabled):
        audio, repaired_impulses = _repair_impulses(audio)

    edge_fade_samples = max(0, int(edge_fade_samples))
    if edge_fade_samples > 0:
        audio = _apply_edge_fade(audio, edge_fade_samples)

    max_abs_before = float(np.max(np.abs(audio))) if audio.size else 0.0
    target_peak = float(target_peak)
    scale = 1.0
    if bool(peak_normalize_enabled) and max_abs_before > target_peak > 0:
        scale = target_peak / max_abs_before
        audio = audio * scale

    # tanh 软限制只作用在保护阈值以上的极端峰值，比硬 clip 更不容易产生爆音。
    if target_peak > 0 and audio.size:
        soft_limit = min(0.98, max(0.5, target_peak * 1.08))
        over = np.abs(audio) > soft_limit
        if np.any(over):
            signed = np.sign(audio[over])
            excess = (np.abs(audio[over]) - soft_limit) / max(1e-6, 1.0 - soft_limit)
            audio[over] = signed * (soft_limit + (1.0 - soft_limit) * np.tanh(excess))

    clipped = np.clip(audio, -1.0, 1.0).astype(np.float32, copy=False)
    clip_ratio = float(np.mean(np.abs(clipped) >= 0.999)) if clipped.size else 0.0
    quality = MossAudioQuality(
        max_abs_before=max_abs_before,
        scale=scale,
        max_abs_after=float(np.max(np.abs(clipped))) if clipped.size else 0.0,
        clip_ratio=clip_ratio,
        repaired_impulses=int(repaired_impulses),
        dc_offset_before=dc_offset_before,
    )
    return clipped, quality


def ensure_audio_shape(waveform, *, channels: int) -> np.ndarray:
    """把任意 waveform 整理成 ``(samples, channels)`` float32。"""

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

    return np.nan_to_num(audio, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32, copy=False)


def _repair_impulses(audio: np.ndarray) -> tuple[np.ndarray, int]:
    """修复孤立瞬态尖峰，避免把正常辅音/爆破音抹掉。"""

    if audio.shape[0] < 3:
        return audio, 0
    repaired = np.array(audio, copy=True)
    total = 0
    for ch in range(repaired.shape[1]):
        y = repaired[:, ch]
        neighbor_avg = 0.5 * (y[:-2] + y[2:])
        residual = y[1:-1] - neighbor_avg
        # 同时要求残差大、绝对振幅大、相邻点没有同向大振幅，尽量只抓“针刺”。
        mask = (np.abs(residual) > 0.42) & (np.abs(y[1:-1]) > 0.55)
        if not np.any(mask):
            continue
        idx = np.nonzero(mask)[0] + 1
        y[idx] = neighbor_avg[mask]
        total += int(idx.size)
    return repaired, total


def _apply_edge_fade(audio: np.ndarray, fade_samples: int) -> np.ndarray:
    if audio.shape[0] <= 2 or fade_samples <= 0:
        return audio
    n = min(int(fade_samples), max(1, audio.shape[0] // 8))
    if n <= 1:
        return audio
    faded = np.array(audio, copy=True)
    fade_in = np.linspace(0.0, 1.0, n, dtype=np.float32).reshape(-1, 1)
    fade_out = np.linspace(1.0, 0.0, n, dtype=np.float32).reshape(-1, 1)
    faded[:n] *= fade_in
    faded[-n:] *= fade_out
    return faded


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


def concat_waveforms(
    waveforms: Iterable[np.ndarray],
    *,
    crossfade_ms: float = 0.0,
    sample_rate: int | None = None,
    channels: int | None = None,
) -> np.ndarray:
    """合并非空波形，可选短 crossfade。"""

    parts = [item for item in waveforms if getattr(item, "size", 0)]
    if not parts:
        raise RuntimeError("MOSS: all segments produced empty audio")
    if channels is None:
        channels = int(parts[0].shape[1]) if np.asarray(parts[0]).ndim == 2 else 1
    prepared = [ensure_audio_shape(item, channels=channels) for item in parts]
    fade_samples = 0
    if sample_rate is not None:
        fade_samples = max(0, int(int(sample_rate) * max(0.0, float(crossfade_ms)) / 1000.0))
    if fade_samples <= 1 or len(prepared) == 1:
        return np.concatenate(prepared).astype(np.float32, copy=False)
    return crossfade_concat(prepared, fade_samples=fade_samples)


def crossfade_concat(waveforms: Iterable[np.ndarray], *, fade_samples: int) -> np.ndarray:
    """用线性短 crossfade 拼接多段音频，减少硬切导致的电流感/顿挫。"""

    parts = [np.asarray(item, dtype=np.float32) for item in waveforms if getattr(item, "size", 0)]
    if not parts:
        raise RuntimeError("MOSS: all segments produced empty audio")
    result = parts[0]
    for part in parts[1:]:
        n = min(max(0, int(fade_samples)), result.shape[0], part.shape[0])
        if n <= 1:
            result = np.concatenate([result, part], axis=0)
            continue
        fade_out = np.linspace(1.0, 0.0, n, dtype=np.float32).reshape(-1, 1)
        fade_in = np.linspace(0.0, 1.0, n, dtype=np.float32).reshape(-1, 1)
        overlap = result[-n:] * fade_out + part[:n] * fade_in
        result = np.concatenate([result[:-n], overlap, part[n:]], axis=0)
    return result.astype(np.float32, copy=False)


def silence_array(seconds: float, *, sample_rate: int, channels: int) -> np.ndarray:
    """生成指定时长的静音波形。"""

    samples = max(0, int(int(sample_rate) * max(0.0, float(seconds))))
    expected_channels = max(1, int(channels))
    if samples <= 0:
        return np.zeros((0, expected_channels), dtype=np.float32)
    return np.zeros((samples, expected_channels), dtype=np.float32)


def amplitude_threshold(db: float) -> float:
    """把 dBFS 阈值转换为线性振幅。"""

    return float(10.0 ** (float(db) / 20.0))


def trim_silence_edges(
    waveform,
    *,
    sample_rate: int,
    channels: int,
    threshold_db: float = -45.0,
    keep_ms: float = 20.0,
) -> tuple[np.ndarray, float, float]:
    """裁掉片段首尾低能量静音，但保留极短气口，避免过度生硬。"""

    audio = ensure_audio_shape(waveform, channels=channels)
    if audio.size == 0:
        return audio, 0.0, 0.0
    threshold = amplitude_threshold(threshold_db)
    envelope = np.max(np.abs(audio), axis=1)
    active = envelope > threshold
    if not np.any(active):
        return audio[:0], audio.shape[0] * 1000.0 / sample_rate, 0.0
    indices = np.flatnonzero(active)
    keep = max(0, int(int(sample_rate) * max(0.0, float(keep_ms)) / 1000.0))
    start = max(0, int(indices[0]) - keep)
    end = min(audio.shape[0], int(indices[-1]) + keep + 1)
    trimmed_start = start * 1000.0 / sample_rate
    trimmed_end = (audio.shape[0] - end) * 1000.0 / sample_rate
    return np.ascontiguousarray(audio[start:end]), trimmed_start, trimmed_end


def compress_long_silence(
    waveform,
    *,
    sample_rate: int,
    channels: int,
    threshold_db: float = -45.0,
    max_silence_ms: float = 900.0,
) -> tuple[np.ndarray, dict[str, float]]:
    """把异常长静音压缩到上限，保留正常句读停顿。"""

    audio = ensure_audio_shape(waveform, channels=channels)
    if audio.size == 0:
        return audio, {"long_silence_count": 0, "max_silence_ms": 0.0, "silence_ratio": 0.0}
    max_samples = max(0, int(int(sample_rate) * max(0.0, float(max_silence_ms)) / 1000.0))
    threshold = amplitude_threshold(threshold_db)
    silence = np.max(np.abs(audio), axis=1) <= threshold
    total_silence = int(np.count_nonzero(silence))
    if max_samples <= 0:
        # 0 表示禁用长静音压缩，保留原始音频内容。
        return np.ascontiguousarray(audio), analyze_silence(
            audio, sample_rate=sample_rate, channels=channels, threshold_db=threshold_db
        )
    parts: list[np.ndarray] = []
    long_count = 0
    max_run = 0
    cursor = 0
    n = audio.shape[0]
    i = 0
    while i < n:
        if not silence[i]:
            i += 1
            continue
        start = i
        while i < n and silence[i]:
            i += 1
        end = i
        run = end - start
        max_run = max(max_run, run)
        if run > max_samples:
            long_count += 1
            if start > cursor:
                parts.append(audio[cursor:start])
            if max_samples > 0:
                parts.append(audio[start : start + max_samples])
            cursor = end
    if cursor < n:
        parts.append(audio[cursor:])
    result = np.concatenate(parts, axis=0) if parts else audio[:0]
    return np.ascontiguousarray(result), {
        "long_silence_count": int(long_count),
        "max_silence_ms": float(max_run * 1000.0 / sample_rate),
        "silence_ratio": float(total_silence / max(1, n)),
    }


def analyze_silence(waveform, *, sample_rate: int, channels: int, threshold_db: float = -45.0) -> dict[str, float]:
    """只分析不改动，供 Admin/脚本展示音频质量。"""

    audio = ensure_audio_shape(waveform, channels=channels)
    if audio.size == 0:
        return {"long_silence_count": 0, "max_silence_ms": 0.0, "silence_ratio": 0.0}
    # 这里把 1 秒以上当作“长静音”统计，真正压缩上限由 config 控制。
    threshold = amplitude_threshold(threshold_db)
    silence = np.max(np.abs(audio), axis=1) <= threshold
    max_run = 0
    long_count = 0
    i = 0
    n = audio.shape[0]
    long_samples = int(sample_rate)
    while i < n:
        if not silence[i]:
            i += 1
            continue
        start = i
        while i < n and silence[i]:
            i += 1
        run = i - start
        max_run = max(max_run, run)
        if run >= long_samples:
            long_count += 1
    return {
        "long_silence_count": int(long_count),
        "max_silence_ms": float(max_run * 1000.0 / sample_rate),
        "silence_ratio": float(np.count_nonzero(silence) / max(1, n)),
    }


def clamp_pause_seconds(seconds: float, *, max_ms: float) -> float:
    """限制 runtime 估计出的 chunk pause，避免长文本出现 2-5 秒空白。"""

    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(value, max(0.0, float(max_ms)) / 1000.0))
