"""Reference-audio upload helpers shared by HTTP and WebSocket routes."""

from __future__ import annotations

import base64
import hashlib
import os
import re
import tempfile
import time
from pathlib import Path

from fastapi import HTTPException

PROMPT_AUDIO_SUFFIXES = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac"}
PROMPT_AUDIO_STALE_SECONDS = 24 * 60 * 60
_PROMPT_AUDIO_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}_[0-9a-f]{16}\.(?:wav|mp3|flac|ogg|m4a|aac)$")


def prompt_audio_temp_dir() -> Path:
    """Return the private root for short-lived prompt/reference audio uploads."""

    return Path(tempfile.gettempdir()) / "angevoice_prompt_audio"


def _safe_prompt_audio_filename(path: str | Path) -> str | None:
    raw = os.fspath(path)
    if not raw or "\x00" in raw:
        return None
    name = raw.replace("\\", "/").rsplit("/", 1)[-1]
    if not _PROMPT_AUDIO_NAME_RE.fullmatch(name):
        return None
    return name


def delete_prompt_audio_path(path: str | Path) -> bool:
    """Delete an internally generated prompt-audio temp file if it is safe.

    User-influenced paths must never be unlinked directly.  Only files under the
    prompt temp root with AngeVoice's generated ``requestid_digest.ext`` naming
    shape are eligible for deletion; symlinks and traversal attempts are ignored.
    """

    name = _safe_prompt_audio_filename(path)
    if name is None:
        return False
    try:
        root = prompt_audio_temp_dir().resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return False
    candidate = root / name
    try:
        if candidate.is_symlink():
            return False
        if not candidate.exists():
            return False
        if not candidate.is_file():
            return False
        candidate.unlink()
        return True
    except OSError:
        return False


def cleanup_stale_prompt_audio_files(temp_dir: Path, *, now: float | None = None) -> int:
    """Remove only stale temporary reference files left behind by interrupted processes."""
    current = time.time() if now is None else float(now)
    removed = 0
    if not temp_dir.exists():
        return removed
    for item in temp_dir.iterdir():
        try:
            if not item.is_file() or item.is_symlink():
                continue
            if current - item.stat().st_mtime < PROMPT_AUDIO_STALE_SECONDS:
                continue
            item.unlink()
            removed += 1
        except OSError:
            continue
    return removed


def _prompt_suffix(filename: str) -> str:
    suffix = Path(filename or "prompt.wav").suffix.lower() or ".wav"
    if suffix not in PROMPT_AUDIO_SUFFIXES:
        raise HTTPException(status_code=400, detail="参考音频仅支持 wav/mp3/flac/ogg/m4a/aac")
    return suffix


async def save_prompt_audio_upload(
    *,
    upload,
    filename: str,
    request_id: str,
    max_bytes: int,
    chunk_bytes: int = 1024 * 1024,
) -> tuple[str | None, str]:
    """Persist a multipart reference upload incrementally with a hard byte cap."""
    suffix = _prompt_suffix(filename)
    temp_dir = prompt_audio_temp_dir()
    temp_dir.mkdir(parents=True, exist_ok=True)
    cleanup_stale_prompt_audio_files(temp_dir)
    digest = hashlib.sha256()
    total = 0
    fd, temp_name = tempfile.mkstemp(prefix=".prompt-", suffix=".tmp", dir=temp_dir)
    target: Path | None = None
    try:
        with os.fdopen(fd, "wb") as handle:
            while True:
                chunk = await upload.read(max(1, min(int(chunk_bytes), int(max_bytes) - total + 1)))
                if not chunk:
                    break
                total += len(chunk)
                if total > int(max_bytes):
                    raise HTTPException(status_code=413, detail=f"参考音频不能超过 {int(max_bytes) // 1024 // 1024}MB")
                digest.update(chunk)
                handle.write(chunk)
            if total == 0:
                return None, ""
            handle.flush()
            os.fsync(handle.fileno())
        hex_digest = digest.hexdigest()
        target = temp_dir / f"{request_id}_{hex_digest[:16]}{suffix}"
        os.replace(temp_name, target)
        return str(target), f"sha256:{hex_digest}"
    finally:
        try:
            Path(temp_name).unlink(missing_ok=True)
        except OSError:
            pass

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

    suffix = _prompt_suffix(filename)

    digest = hashlib.sha256(content).hexdigest()
    temp_dir = prompt_audio_temp_dir()
    temp_dir.mkdir(parents=True, exist_ok=True)
    cleanup_stale_prompt_audio_files(temp_dir)
    target = temp_dir / f"{request_id}_{digest[:16]}{suffix}"
    fd, temp_name = tempfile.mkstemp(prefix=".prompt-", suffix=".tmp", dir=temp_dir)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, target)
    finally:
        try:
            Path(temp_name).unlink(missing_ok=True)
        except OSError:
            pass
    return str(target), f"sha256:{digest}"


def validate_reference_audio_duration(path: str | Path, *, max_seconds: float) -> float:
    """Validate a reference recording without silently cropping user audio."""
    try:
        import soundfile as sf
        info = sf.info(str(path))
        duration = float(info.frames / info.samplerate) if info.samplerate else 0.0
    except Exception as exc:
        raise HTTPException(status_code=400, detail="无法读取参考音频，请上传有效音频文件") from exc
    if duration > float(max_seconds):
        raise HTTPException(
            status_code=400,
            detail=f"参考录音最长支持 {float(max_seconds):g} 秒，当前 {duration:.2f} 秒。ZipVoice 官方建议单人参考音频少于 3 秒，请裁剪后重试。",
        )
    return duration


def decode_prompt_audio_base64(value: str, *, max_bytes: int | None = None) -> bytes:
    """Decode WebSocket reference audio while limiting allocation before decode.

    The incoming JSON text is already held by the WebSocket stack, but rejecting an
    oversized base64 payload before decoding avoids allocating a second large byte
    buffer beyond the configured reference-audio limit.
    """
    raw = str(value or "").strip()
    if not raw:
        return b""
    if "," in raw and raw.split(",", 1)[0].lower().startswith("data:"):
        raw = raw.split(",", 1)[1]
    if max_bytes is not None:
        maximum = int(max_bytes)
        max_encoded_chars = 4 * ((maximum + 2) // 3)
        if len(raw) > max_encoded_chars:
            raise HTTPException(status_code=413, detail=f"参考音频不能超过 {maximum // 1024 // 1024}MB")
    try:
        decoded = base64.b64decode(raw, validate=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="参考音频 base64 无效") from exc
    if max_bytes is not None and len(decoded) > int(max_bytes):
        raise HTTPException(status_code=413, detail=f"参考音频不能超过 {int(max_bytes) // 1024 // 1024}MB")
    return decoded
