"""Reference-audio upload helpers shared by HTTP and WebSocket routes."""

from __future__ import annotations

import base64
import hashlib
import tempfile
from pathlib import Path

from fastapi import HTTPException

PROMPT_AUDIO_SUFFIXES = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac"}


def save_prompt_audio_bytes(
    *,
    content: bytes,
    filename: str,
    request_id: str,
    max_bytes: int,
) -> tuple[str | None, str]:
    if not content:
        return None, ""
    if len(content) > int(max_bytes):
        raise HTTPException(status_code=413, detail=f"参考音频不能超过 {int(max_bytes) // 1024 // 1024}MB")

    suffix = Path(filename or "prompt.wav").suffix.lower() or ".wav"
    if suffix not in PROMPT_AUDIO_SUFFIXES:
        raise HTTPException(status_code=400, detail="参考音频仅支持 wav/mp3/flac/ogg/m4a/aac")

    digest = hashlib.sha256(content).hexdigest()
    temp_dir = Path(tempfile.gettempdir()) / "angevoice_prompt_audio"
    temp_dir.mkdir(parents=True, exist_ok=True)
    target = temp_dir / f"{request_id}_{digest[:16]}{suffix}"
    target.write_bytes(content)
    return str(target), f"sha256:{digest}"


def decode_prompt_audio_base64(value: str) -> bytes:
    raw = str(value or "").strip()
    if not raw:
        return b""
    if "," in raw and raw.split(",", 1)[0].lower().startswith("data:"):
        raw = raw.split(",", 1)[1]
    try:
        return base64.b64decode(raw, validate=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="参考音频 base64 无效") from exc
