"""Pure MOSS prompt metadata helpers."""

from __future__ import annotations

import hashlib
from pathlib import Path


def prompt_audio_cache_key(
    *,
    voice: str,
    default_voice: str,
    prompt_audio_path: str | None,
    max_seconds: float,
    sample_rate: int,
    channels: int,
) -> str:
    """Generate a deterministic cache key for MOSS prompt metadata."""

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


__all__ = ["prompt_audio_cache_key"]
