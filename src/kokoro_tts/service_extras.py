"""AngeVoice 可选服务端点。

批量合成、管理接口、MP3 转码等产品功能集中放在这里，避免
``server.py`` 继续膨胀。
"""

import asyncio
import os
import json
import logging
import shutil
import subprocess
import tempfile
import threading
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Callable, Optional

from fastapi import Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .admin_auth import make_verify_admin
from .audio_formats import (
    ffmpeg_effective_enabled,
    normalize_response_format as normalize_public_audio_format,
    supported_response_formats,
    transcode_wav_bytes,
)
from .validation import validate_model_speed, validate_tts_text

logger = logging.getLogger(__name__)

ALLOWED_MP3_BITRATES = {"64k", "96k", "128k", "160k", "192k", "256k", "320k"}
_fallback_stats_lock = threading.Lock()



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
    class _Cfg:
        ffmpeg_enabled = True
        mp3_enabled = True
        ffmpeg_binary = "ffmpeg"
        ffmpeg_timeout_seconds = 30.0
        mp3_bitrate = bitrate
        audio_opus_bitrate = "32k"
        audio_aac_bitrate = "96k"

    return transcode_wav_bytes(wav_bytes, _Cfg(), "mp3")[0]


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
    """Compatibility entry; new application assembly uses register_service_routes."""
    def inc_stat(name: str, delta=1) -> None:
        if increment_stat is not None:
            increment_stat(name, delta)
            return
        with _fallback_stats_lock:
            stats[name] = stats.get(name, 0) + delta

    def clear_legacy_cache() -> int:
        if cache_clear is not None:
            return cache_clear()
        size = len(tts_cache)
        tts_cache.clear()
        return size

    def normalize_legacy_model(model):
        resolved = getattr(getattr(app, "state", object()), "angevoice", None)
        return resolved.model_manager.normalize_model_id(model) if resolved is not None else model

    _register_batch_routes(
        app=app, cfg=cfg, verify_api_key=verify_api_key,
        synthesize_threaded=synthesize_threaded, new_request_id=new_request_id,
        mark_request=mark_request, finish_request=finish_request,
        inc_stat=inc_stat, normalize_model_id=normalize_legacy_model,
    )
    _register_admin_resource_routes(app=app, cfg=cfg, cache_clear=clear_legacy_cache)
    _register_format_routes(app=app, cfg=cfg)


def register_service_routes(*, app, state, verify_api_key):
    """Compose route domains once; handlers receive only their dependencies."""
    _register_batch_routes(
        app=app, cfg=state.cfg, verify_api_key=verify_api_key,
        synthesize_threaded=state.synthesize_response_threaded,
        new_request_id=state.new_request_id, mark_request=state.mark_request,
        finish_request=state.finish_request, inc_stat=state.inc_stat,
        normalize_model_id=state.model_manager.normalize_model_id,
    )
    _register_admin_resource_routes(app=app, cfg=state.cfg, cache_clear=state.cache_clear)
    _register_format_routes(app=app, cfg=state.cfg)


def _register_batch_routes(
    *, app, cfg, verify_api_key, synthesize_threaded, new_request_id,
    mark_request, finish_request, inc_stat, normalize_model_id,
):
    """Register batch synthesis without cache, engine or request-table access."""
    def normalize_extra_format(fmt: str) -> str:
        return normalize_public_audio_format(fmt, cfg)

    async def synthesize_optional_mp3(text: str, voice: str, speed: float, fmt: str, request_id: str, model: str | None = None):
        fmt = normalize_extra_format(fmt)
        text = validate_tts_text(text, cfg)
        model = model or None
        model = normalize_model_id(model)
        speed = validate_model_speed(model, speed)
        return await synthesize_threaded(text, voice, speed, fmt, request_id, model)

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
        ext = {"pcm": "pcm", "ogg_opus": "ogg", "m4a": "m4a", "mp3": "mp3", "wav": "wav"}.get(fmt, fmt)
        batch_id = new_request_id()
        inc_stat("batch_requests_total")
        inc_stat("batch_items_total", len(req.items))
        mark_request(batch_id, "queued", batch=True, items=len(req.items), format=fmt)

        batch_sem = asyncio.Semaphore(max(1, int(getattr(cfg, "batch_concurrency", 1))))

        async def run_item(index: int, item: BatchItem):
            item_id = f"{batch_id}-{index + 1:03d}"
            voice = item.voice or req.voice
            speed = item.speed if item.speed is not None else req.speed
            model = item.model or req.model
            filename = _safe_zip_filename(item.filename, index, ext)
            try:
                text = validate_tts_text(item.text, cfg)
            except HTTPException as exc:
                return index, None, {"index": index, "status": "error", "error": exc.detail}
            async with batch_sem:
                try:
                    audio_bytes, _media_type = await synthesize_optional_mp3(text, voice, speed, fmt, item_id, model)
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


def _register_admin_resource_routes(*, app, cfg, cache_clear):
    """Register admin resources with an authenticated cache operation."""
    verify_admin = make_verify_admin(cfg)

    @app.delete("/admin/cache")
    async def clear_cache(request: Request):
        await verify_admin(request)
        size = cache_clear()
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
        voices_root = cfg.voices_dir.resolve()
        target = voices_root / filename
        # basename 检查防止常规遍历；解析父目录和符号链接
        # 检查防止可写卷中预先创建的链接重定向写入。
        if target.parent.resolve() != voices_root:
            raise HTTPException(status_code=400, detail="Invalid voice file path")
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise HTTPException(status_code=409, detail="Voice target is not a regular file")
        # 即使底层文件系统包含异常链接或挂载重定向，
        # 也将解析后的目标保持在配置的音色根目录内。
        try:
            target.resolve(strict=False).relative_to(voices_root)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid voice file path") from exc
        temp_name = ""
        try:
            with tempfile.NamedTemporaryFile(prefix=".upload-", suffix=".pt.tmp", dir=voices_root, delete=False) as handle:
                temp_name = handle.name
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temp_name, 0o600)
            os.replace(temp_name, target)
        finally:
            if temp_name:
                try:
                    Path(temp_name).unlink(missing_ok=True)
                except OSError:
                    logger.debug("Unable to clean voice upload temp file", exc_info=True)
        return {"ok": True, "voice": target.stem, "bytes": len(content)}


def _register_format_routes(*, app, cfg):
    """Register format discovery without synthesis or mutable service state."""
    @app.get("/v1/audio/formats")
    async def audio_formats():
        formats = supported_response_formats(cfg)
        bitrate_ok = True
        try:
            _normalize_mp3_bitrate(getattr(cfg, "mp3_bitrate", "192k"))
        except ValueError:
            bitrate_ok = False
        binary = str(getattr(cfg, "ffmpeg_binary", "ffmpeg") or "ffmpeg")
        return {
            "formats": formats,
            "ffmpeg_enabled": ffmpeg_effective_enabled(cfg),
            "ffmpeg_available": bool(shutil.which(binary)),
            "ffmpeg_binary": binary,
            "mp3_enabled": ffmpeg_effective_enabled(cfg),
            "mp3_requires_ffmpeg": True,
            "mp3_available": bool(shutil.which(binary)),
            "mp3_bitrate": getattr(cfg, "mp3_bitrate", "192k"),
            "mp3_bitrate_valid": bitrate_ok,
            "opus_bitrate": getattr(cfg, "audio_opus_bitrate", "32k"),
            "aac_bitrate": getattr(cfg, "audio_aac_bitrate", "96k"),
        }
