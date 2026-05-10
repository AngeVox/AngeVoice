"""MOSS 参考音频处理与 prompt code 缓存。"""

from __future__ import annotations

import hashlib
import tempfile
from collections import OrderedDict
from contextlib import suppress
from pathlib import Path
from threading import Lock


def prompt_audio_cache_key(*, voice: str, default_voice: str, prompt_audio_path: str | None, max_seconds: float, sample_rate: int, channels: int) -> str:
    """生成参考音频缓存键。"""

    selected_voice = voice or default_voice
    if not prompt_audio_path:
        return f"voice:{selected_voice}"
    path = Path(prompt_audio_path).expanduser()
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        digest.update(str(path).encode("utf-8", "ignore"))
    return f"prompt:{digest.hexdigest()}:voice:{selected_voice}:maxsec:{float(max_seconds):.3f}:sr:{int(sample_rate)}:ch:{int(channels)}"


def prepare_prompt_audio(prompt_audio_path: str | None, *, max_seconds: float, sample_rate: int, channels: int, logger=None) -> tuple[str | None, str | None]:
    """按 MOSS 目标采样率和通道数裁剪参考音频。"""

    if not prompt_audio_path:
        return None, None
    if float(max_seconds or 0) <= 0:
        return prompt_audio_path, None
    try:
        import torch
        import torchaudio
    except Exception:
        if logger:
            logger.debug("torchaudio 不可用，直接使用原始参考音频", exc_info=True)
        return prompt_audio_path, None

    source = Path(prompt_audio_path).expanduser().resolve()
    try:
        waveform, source_sample_rate = torchaudio.load(str(source))
    except Exception:
        if logger:
            logger.debug("读取参考音频失败，直接使用原始文件", exc_info=True)
        return prompt_audio_path, None

    target_sample_rate = int(sample_rate)
    target_channels = max(1, int(channels))
    waveform = waveform.to(torch.float32)
    if int(source_sample_rate) != target_sample_rate:
        waveform = torchaudio.functional.resample(waveform, int(source_sample_rate), target_sample_rate)

    max_samples = int(target_sample_rate * float(max_seconds))
    if max_samples > 0 and int(waveform.shape[-1]) > max_samples:
        if logger:
            logger.info("裁剪 MOSS 参考音频：%.2fs -> %.2fs", float(waveform.shape[-1]) / float(target_sample_rate), float(max_seconds))
        waveform = waveform[..., :max_samples]
    if int(waveform.shape[0]) > target_channels:
        waveform = waveform.mean(dim=0, keepdim=True)
    if int(waveform.shape[0]) < target_channels:
        waveform = waveform.repeat(target_channels, 1)
    waveform = torch.clamp(waveform, -1.0, 1.0)

    temp_dir = Path(tempfile.gettempdir()) / "angevoice_moss_prompt"
    temp_dir.mkdir(parents=True, exist_ok=True)
    target = temp_dir / f"{source.stem}_{hashlib.sha1(str(source).encode()).hexdigest()[:10]}_{int(float(max_seconds) * 1000)}ms.wav"
    torchaudio.save(str(target), waveform.cpu(), target_sample_rate)
    return str(target), str(target)


def resolve_prompt_audio_codes_cached(*, runtime, cache: OrderedDict[str, list[list[int]]], cache_lock: Lock, voice: str, default_voice: str, prompt_audio_path: str | None, max_items: int, max_seconds: float, sample_rate: int, channels: int, logger=None) -> list[list[int]]:
    """解析并缓存 MOSS prompt audio codes。"""

    key = prompt_audio_cache_key(voice=voice, default_voice=default_voice, prompt_audio_path=prompt_audio_path, max_seconds=max_seconds, sample_rate=sample_rate, channels=channels)
    with cache_lock:
        cached = cache.get(key)
        if cached is not None:
            cache.move_to_end(key)
            return cached

    prepared_path, cleanup_path = prepare_prompt_audio(prompt_audio_path, max_seconds=max_seconds, sample_rate=sample_rate, channels=channels, logger=logger)
    try:
        codes = runtime.resolve_prompt_audio_codes(voice=voice or default_voice, prompt_audio_path=prepared_path)
    finally:
        if cleanup_path:
            with suppress(OSError):
                Path(cleanup_path).unlink()

    if int(max_items) > 0:
        with cache_lock:
            cache[key] = codes
            cache.move_to_end(key)
            while len(cache) > int(max_items):
                cache.popitem(last=False)
    return codes
