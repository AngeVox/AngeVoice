"""AngeVoice 可选服务端点。

批量合成、管理接口、MP3 转码等产品功能集中放在这里，避免
``server.py`` 继续膨胀。
"""

import asyncio
import base64
import binascii
import hmac
import os
import json
import logging
import shutil
import subprocess
import threading
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Callable, Optional

from fastapi import Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

ALLOWED_MP3_BITRATES = {"64k", "96k", "128k", "160k", "192k", "256k", "320k"}
_fallback_stats_lock = threading.Lock()


def _admin_credential_candidates(value: str) -> list[bytes]:
    candidates: list[bytes] = []
    for encoding in ("utf-8", "latin-1"):
        try:
            encoded = value.encode(encoding)
        except UnicodeEncodeError:
            continue
        if encoded not in candidates:
            candidates.append(encoded)
    return candidates


class BatchItem(BaseModel):
    text: str = Field(..., description="待合成文本")
    model: Optional[str] = Field(default=None, description="模型 ID")
    voice: Optional[str] = Field(default=None, description="音色名称")
    speed: Optional[float] = Field(default=None, ge=0.5, le=2.0, description="语速")
    filename: Optional[str] = Field(default=None, description="ZIP 内文件名")


class BatchTTSRequest(BaseModel):
    items: list[BatchItem]
    voice: str = "zm_010"
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    response_format: str = "wav"
    model: Optional[str] = None


def _safe_zip_filename(name: Optional[str], index: int, ext: str) -> str:
    raw = (name or f"speech_{index + 1:03d}").strip()
    raw = raw.replace("/", "_").replace("\\", "_")
    raw = "".join(ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in raw)
    if not raw:
        raw = f"speech_{index + 1:03d}"
    if not raw.lower().endswith(f".{ext}"):
        raw = f"{raw}.{ext}"
    return raw


def _normalize_mp3_bitrate(bitrate: str = "192k") -> str:
    value = (bitrate or "192k").strip().lower()
    if value not in ALLOWED_MP3_BITRATES:
        raise ValueError(f"Unsupported MP3 bitrate: {bitrate}. Allowed: {', '.join(sorted(ALLOWED_MP3_BITRATES))}")
    return value


def _wav_to_mp3(wav_bytes: bytes, bitrate: str = "192k") -> bytes:
    bitrate = _normalize_mp3_bitrate(bitrate)
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found")
    proc = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "wav",
            "-i",
            "pipe:0",
            "-codec:a",
            "libmp3lame",
            "-b:a",
            bitrate,
            "-f",
            "mp3",
            "pipe:1",
        ],
        input=wav_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="ignore") or "ffmpeg mp3 conversion failed"
        raise RuntimeError(err)
    return proc.stdout


def register_extra_routes(
    *,
    app,
    cfg,
    eng,
    verify_api_key,
    tts_cache,
    active_requests,
    stats,
    synthesize_threaded: Callable,
    new_request_id: Callable[[], str],
    normalize_response_format: Callable[[str], str],
    mark_request: Callable,
    finish_request: Callable,
    increment_stat: Callable[[str, object], None] | None = None,
    cache_clear: Callable[[], int] | None = None,
    cache_size: Callable[[], int] | None = None,
):
    """注册 AngeVoice 可选服务路由。"""
    def inc_stat(name: str, delta=1) -> None:
        if increment_stat is not None:
            increment_stat(name, delta)
            return
        with _fallback_stats_lock:
            stats[name] = stats.get(name, 0) + delta

    async def verify_admin(request: Request):
        if not cfg.admin_enabled:
            raise HTTPException(status_code=404, detail="Admin API disabled")

        auth = request.headers.get("Authorization", "")
        if cfg.api_key and auth.lower().startswith("bearer "):
            token = auth[7:].strip()
            if hmac.compare_digest(token, cfg.api_key or ""):
                return

        admin_password = (os.environ.get("ANGEVOICE_ADMIN_PASSWORD") or "").strip()
        if not admin_password:
            raise HTTPException(status_code=503, detail="Admin password is not configured")

        if auth.lower().startswith("basic "):
            raw = auth.split(" ", 1)[1].strip()
            try:
                decoded = base64.b64decode(raw, validate=True)
                username_bytes, password_bytes = decoded.split(b":", 1)
            except (binascii.Error, ValueError):
                username_bytes, password_bytes = b"", b""
            expected_username = os.environ.get("ANGEVOICE_ADMIN_USERNAME", "admin") or "admin"
            username_ok = any(hmac.compare_digest(username_bytes, item) for item in _admin_credential_candidates(expected_username))
            password_ok = any(hmac.compare_digest(password_bytes, item) for item in _admin_credential_candidates(admin_password))
            if username_ok and password_ok:
                return

        raise HTTPException(
            status_code=401,
            detail="Admin login required",
            headers={"WWW-Authenticate": 'Basic realm="AngeVoice Admin", charset="UTF-8"'},
        )

    def normalize_extra_format(fmt: str) -> str:
        fmt = (fmt or "wav").lower()
        if fmt == "mp3":
            if not cfg.mp3_enabled:
                raise HTTPException(status_code=400, detail="MP3 output disabled. Set KOKORO_MP3_ENABLED=true and install ffmpeg.")
            return "mp3"
        return normalize_response_format(fmt)

    async def synthesize_optional_mp3(text: str, voice: str, speed: float, fmt: str, request_id: str, model: str | None = None):
        fmt = normalize_extra_format(fmt)
        if fmt != "mp3":
            return await synthesize_threaded(text, voice, speed, fmt, request_id, model)
        wav_bytes, _ = await synthesize_threaded(text, voice, speed, "wav", request_id, model)
        try:
            mp3_bytes = _wav_to_mp3(wav_bytes, getattr(cfg, "mp3_bitrate", "192k"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception:
            logger.exception("MP3 conversion failed")
            raise HTTPException(status_code=500, detail="MP3 conversion failed")
        return mp3_bytes, "audio/mpeg"

    @app.post("/v1/audio/batch")
    async def batch_tts(req: BatchTTSRequest, _=Depends(verify_api_key)):
        """批量合成多条文本并返回 ZIP 文件。"""
        if not cfg.batch_enabled:
            raise HTTPException(status_code=404, detail="Batch API disabled")
        if not req.items:
            raise HTTPException(status_code=400, detail="items cannot be empty")
        if len(req.items) > cfg.batch_max_items:
            raise HTTPException(status_code=400, detail=f"too many items, max {cfg.batch_max_items}")

        fmt = normalize_extra_format(req.response_format)
        ext = "pcm" if fmt == "pcm" else fmt
        batch_id = new_request_id()
        inc_stat("batch_requests_total")
        inc_stat("batch_items_total", len(req.items))
        mark_request(batch_id, "queued", batch=True, items=len(req.items), format=fmt)

        batch_sem = asyncio.Semaphore(max(1, int(getattr(cfg, "batch_concurrency", 1))))

        async def run_item(index: int, item: BatchItem):
            if not item.text:
                return index, None, {"index": index, "status": "error", "error": "text is empty"}
            item_id = f"{batch_id}-{index + 1:03d}"
            voice = item.voice or req.voice
            speed = item.speed if item.speed is not None else req.speed
            model = item.model or req.model
            filename = _safe_zip_filename(item.filename, index, ext)
            async with batch_sem:
                try:
                    audio_bytes, _media_type = await synthesize_optional_mp3(item.text, voice, speed, fmt, item_id, model)
                    return index, (filename, audio_bytes), {"index": index, "status": "ok", "filename": filename, "bytes": len(audio_bytes)}
                except HTTPException as exc:
                    return index, None, {"index": index, "status": "error", "error": exc.detail}
                except Exception:
                    logger.exception("Batch synthesis item failed")
                    return index, None, {"index": index, "status": "error", "error": "synthesis failed"}

        results = await asyncio.gather(*(run_item(index, item) for index, item in enumerate(req.items)))
        results.sort(key=lambda row: row[0])

        manifest = []
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for _index, payload, entry in results:
                if payload is not None:
                    filename, audio_bytes = payload
                    zf.writestr(filename, audio_bytes)
                manifest.append(entry)
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

        finish_request(batch_id, "done", items=len(req.items))
        zip_buffer.seek(0)
        return StreamingResponse(
            zip_buffer,
            media_type="application/zip",
            headers={
                "X-Request-ID": batch_id,
                "Content-Disposition": f'attachment; filename="angevoice_batch_{batch_id}.zip"',
            },
        )

    @app.delete("/admin/cache")
    async def clear_cache(request: Request):
        await verify_admin(request)
        if cache_clear is not None:
            size = cache_clear()
        else:
            size = len(tts_cache)
            tts_cache.clear()
        return {"ok": True, "cleared": size}

    @app.get("/admin/voices")
    async def admin_voices(request: Request):
        await verify_admin(request)
        return {"voices": cfg.get_voices(), "voices_dir": str(cfg.voices_dir)}

    @app.post("/admin/voices/upload")
    async def upload_voice(request: Request, file: UploadFile = File(...)):
        await verify_admin(request)
        if not cfg.voice_upload_enabled:
            raise HTTPException(status_code=404, detail="Voice upload disabled")
        filename = Path(file.filename or "").name
        if not filename.endswith(".pt"):
            raise HTTPException(status_code=400, detail="Only .pt voice files are accepted")
        max_bytes = int(getattr(cfg, "voice_upload_max_bytes", 10 * 1024 * 1024))
        content = await file.read(max_bytes + 1)
        if len(content) > max_bytes:
            raise HTTPException(status_code=413, detail=f"Voice file too large, max {max_bytes} bytes")
        if not content:
            raise HTTPException(status_code=400, detail="Empty file")
        cfg.voices_dir.mkdir(parents=True, exist_ok=True)
        target = cfg.voices_dir / filename
        target.write_bytes(content)
        return {"ok": True, "voice": target.stem, "bytes": len(content), "path": str(target)}

    @app.get("/v1/audio/formats")
    async def audio_formats():
        formats = ["wav", "pcm"]
        if cfg.mp3_enabled:
            formats.append("mp3")
        bitrate_ok = True
        try:
            _normalize_mp3_bitrate(getattr(cfg, "mp3_bitrate", "192k"))
        except ValueError:
            bitrate_ok = False
        return {
            "formats": formats,
            "mp3_enabled": cfg.mp3_enabled,
            "mp3_requires_ffmpeg": True,
            "mp3_available": bool(shutil.which("ffmpeg")),
            "mp3_bitrate": getattr(cfg, "mp3_bitrate", "192k"),
            "mp3_bitrate_valid": bitrate_ok,
        }
