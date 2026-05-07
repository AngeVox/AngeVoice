"""Runtime state and shared service helpers for AngeVoice."""

import asyncio
import hashlib
import logging
import re
import threading
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Callable

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool

from .audio import encode_audio_segment
from .config import TTSConfig
from .engine import TTSEngine
from .engine_manager import EngineManager

logger = logging.getLogger(__name__)


class ServiceState:
    """Mutable runtime state for one AngeVoice FastAPI application."""

    def __init__(self, cfg: TTSConfig, eng: TTSEngine | None = None, model_manager: EngineManager | None = None):
        self.cfg = cfg
        self.model_manager = model_manager or EngineManager(cfg, initial_engine=eng)
        self.eng = eng or self.model_manager.get_engine(self.model_manager.current_model_id, load=False)
        self.tts_semaphore = asyncio.Semaphore(max(1, int(cfg.max_concurrent_requests)))
        self.tts_cache: OrderedDict[str, tuple[bytes, str]] = OrderedDict()
        self.cache_lock = threading.Lock()
        self.active_requests: dict[str, dict] = {}
        self.cancelled_requests: set[str] = set()
        self.stats_lock = threading.Lock()
        self.output_lock = threading.Lock()
        self.stats = {
            "requests_total": 0,
            "requests_ok": 0,
            "requests_error": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "characters_total": 0,
            "audio_bytes_total": 0,
            "synthesis_seconds_total": 0.0,
            "ws_cancelled_total": 0,
            "outputs_saved_total": 0,
            "started_at": time.time(),
        }

    def inc_stat(self, name: str, delta=1) -> None:
        with self.stats_lock:
            self.stats[name] = self.stats.get(name, 0) + delta

    def snapshot_stats(self) -> dict:
        with self.stats_lock:
            return dict(self.stats)

    def new_request_id(self) -> str:
        return uuid.uuid4().hex[:12]

    def cache_key(self, model_id: str, text: str, voice: str, speed: float, fmt: str, prompt_audio_id: str = "") -> str:
        payload = f"{model_id}\0{voice}\0{float(speed):.3f}\0{fmt}\0{prompt_audio_id}\0{text}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def prompt_audio_cache_id(self, model_id: str, prompt_audio_id: str = "") -> str:
        if prompt_audio_id:
            return str(prompt_audio_id)
        if not str(model_id or "").startswith("moss-nano") or not self.cfg.moss_prompt_audio_path:
            return ""
        path = Path(self.cfg.moss_prompt_audio_path).expanduser()
        try:
            stat = path.stat()
            return f"path:{path.resolve()}:{stat.st_mtime_ns}:{stat.st_size}"
        except OSError:
            return f"path:{path}"

    def engine_supports_voice_clone(self, eng) -> bool:
        metadata = getattr(eng, "metadata", None)
        if not callable(metadata):
            return False
        try:
            data = metadata()
        except Exception:
            logger.debug("Failed to read engine clone metadata", exc_info=True)
            return False
        modes = data.get("modes") if isinstance(data, dict) else []
        return bool(data.get("voice_clone_supported")) or (isinstance(modes, list) and "voice_clone" in modes)

    def cache_get(self, key: str):
        if not self.cfg.cache_enabled or self.cfg.cache_max_items <= 0:
            return None
        with self.cache_lock:
            item = self.tts_cache.get(key)
            if item is not None:
                self.tts_cache.move_to_end(key)
        if item is None:
            self.inc_stat("cache_misses")
            return None
        self.inc_stat("cache_hits")
        return item

    def cache_set(self, key: str, value: tuple[bytes, str]) -> None:
        if not self.cfg.cache_enabled or self.cfg.cache_max_items <= 0:
            return
        with self.cache_lock:
            self.tts_cache[key] = value
            self.tts_cache.move_to_end(key)
            while len(self.tts_cache) > self.cfg.cache_max_items:
                self.tts_cache.popitem(last=False)

    def cache_size(self) -> int:
        with self.cache_lock:
            return len(self.tts_cache)

    def cache_clear(self) -> int:
        with self.cache_lock:
            size = len(self.tts_cache)
            self.tts_cache.clear()
            return size

    def mark_request(self, request_id: str, status: str, **extra) -> None:
        if not self.cfg.queue_status_enabled:
            return
        item = self.active_requests.setdefault(
            request_id,
            {"id": request_id, "created_at": time.time(), "status": status},
        )
        item.update({"status": status, "updated_at": time.time(), **extra})

    def finish_request(self, request_id: str, status: str, **extra) -> None:
        self.mark_request(request_id, status, **extra)
        if self.cfg.queue_status_enabled and len(self.active_requests) > 100:
            oldest = sorted(self.active_requests.items(), key=lambda kv: kv[1].get("updated_at", 0))[:20]
            for key, _ in oldest:
                self.active_requests.pop(key, None)
        if status in {"done", "error", "timeout", "cancelled"}:
            self.cancelled_requests.discard(request_id)

    def is_cancelled(self, request_id: str) -> bool:
        return request_id in self.cancelled_requests

    def request_cancel(self, request_id: str) -> bool:
        known = request_id in self.active_requests
        self.cancelled_requests.add(request_id)
        self.inc_stat("ws_cancelled_total")
        self.mark_request(request_id, "cancelling")
        return known

    def normalize_response_format(self, fmt: str) -> str:
        fmt = (fmt or "wav").lower()
        if fmt in {"wav", "pcm"}:
            return fmt
        if fmt == "mp3" and getattr(self.cfg, "mp3_enabled", False):
            return fmt
        if fmt == "mp3":
            raise HTTPException(status_code=400, detail="MP3 output disabled. Set KOKORO_MP3_ENABLED=true and install ffmpeg.")
        supported = "wav, pcm" + (", mp3" if getattr(self.cfg, "mp3_enabled", False) else "")
        raise HTTPException(status_code=400, detail=f"Unsupported response_format. Currently supported: {supported}")

    def _safe_filename_part(self, value: str, fallback: str = "item") -> str:
        value = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip()).strip("._")
        return value[:80] or fallback

    def save_generated_output(
        self,
        *,
        request_id: str,
        audio_bytes: bytes,
        response_format: str,
        media_type: str,
        model_id: str,
        voice: str,
    ) -> Path | None:
        if not self.cfg.save_outputs:
            return None
        if not audio_bytes:
            return None
        fmt = self.normalize_response_format(response_format)
        if media_type == "audio/mpeg":
            ext = "mp3"
        elif fmt == "pcm" or media_type == "audio/pcm":
            ext = "pcm_s16le"
        else:
            ext = "wav"
        day = time.strftime("%Y%m%d")
        output_dir = Path(self.cfg.output_dir).expanduser() / day
        timestamp = time.strftime("%H%M%S")
        filename = "_".join(
            [
                timestamp,
                self._safe_filename_part(request_id, "request"),
                self._safe_filename_part(model_id, "model"),
                self._safe_filename_part(voice, "voice"),
            ]
        )
        target = output_dir / f"{filename}.{ext}"
        with self.output_lock:
            output_dir.mkdir(parents=True, exist_ok=True)
            target.write_bytes(audio_bytes)
            self._prune_outputs_locked()
        self.inc_stat("outputs_saved_total")
        return target

    def _prune_outputs_locked(self) -> None:
        max_files = int(getattr(self.cfg, "output_max_files", 0) or 0)
        if max_files <= 0:
            return
        root = Path(self.cfg.output_dir).expanduser()
        if not root.exists():
            return
        files = [
            item
            for item in root.rglob("*")
            if item.is_file() and item.suffix.lower() in {".wav", ".mp3", ".pcm_s16le"}
        ]
        overflow = len(files) - max_files
        if overflow <= 0:
            return
        files.sort(key=lambda item: item.stat().st_mtime)
        for item in files[:overflow]:
            try:
                item.unlink()
            except OSError:
                logger.debug("Failed to prune output file %s", item, exc_info=True)

    def synthesize_response_bytes(
        self,
        text: str,
        voice: str,
        speed: float,
        fmt: str,
        model_id: str | None = None,
        prompt_audio_path: str | None = None,
        prompt_audio_id: str = "",
    ) -> tuple[bytes, str]:
        fmt = self.normalize_response_format(fmt)
        resolved_model = self.model_manager.normalize_model_id(model_id)
        prompt_key = self.prompt_audio_cache_id(resolved_model, prompt_audio_id)
        key = self.cache_key(resolved_model, text, voice, speed, fmt, prompt_key)
        cached = self.cache_get(key)
        if cached is not None:
            return cached

        with self.model_manager.borrow(resolved_model) as eng:
            prompt_kwargs = {}
            if prompt_audio_path:
                if not self.engine_supports_voice_clone(eng):
                    raise HTTPException(status_code=400, detail="当前模型不支持参考音频克隆")
                prompt_kwargs["prompt_audio_path"] = prompt_audio_path
            if fmt == "pcm":
                wav = eng.synthesize_array(text=text, voice=voice, speed=speed, **prompt_kwargs)
                sample_rate = int(getattr(eng, "sample_rate", self.cfg.sample_rate))
                result = (encode_audio_segment(wav, "pcm_s16le", sample_rate), "audio/pcm")
            elif fmt == "mp3":
                from .service_extras import _wav_to_mp3
                wav_bytes = eng.synthesize(text=text, voice=voice, speed=speed, **prompt_kwargs)
                result = (_wav_to_mp3(wav_bytes, getattr(self.cfg, "mp3_bitrate", "192k")), "audio/mpeg")
            else:
                result = (eng.synthesize(text=text, voice=voice, speed=speed, **prompt_kwargs), "audio/wav")
        self.cache_set(key, result)
        return result

    async def synthesize_response_threaded(
        self,
        text: str,
        voice: str,
        speed: float,
        fmt: str,
        request_id: str,
        model_id: str | None = None,
        prompt_audio_path: str | None = None,
        prompt_audio_id: str = "",
    ):
        start = time.perf_counter()
        resolved_model = self.model_manager.normalize_model_id(model_id)
        self.inc_stat("requests_total")
        self.inc_stat("characters_total", len(text or ""))
        self.mark_request(
            request_id,
            "queued",
            voice=voice,
            format=fmt,
            model=resolved_model,
            chars=len(text or ""),
            voice_clone=bool(prompt_audio_path),
        )
        try:
            async with self.tts_semaphore:
                if self.is_cancelled(request_id):
                    self.finish_request(request_id, "cancelled")
                    raise HTTPException(status_code=499, detail="Request cancelled")
                self.mark_request(request_id, "running")
                result = await asyncio.wait_for(
                    run_in_threadpool(
                        self.synthesize_response_bytes,
                        text,
                        voice,
                        speed,
                        fmt,
                        resolved_model,
                        prompt_audio_path,
                        prompt_audio_id,
                    ),
                    timeout=self.cfg.request_timeout_seconds,
                )
            elapsed = time.perf_counter() - start
            self.inc_stat("requests_ok")
            self.inc_stat("audio_bytes_total", len(result[0]))
            self.inc_stat("synthesis_seconds_total", elapsed)
            saved_path = self.save_generated_output(
                request_id=request_id,
                audio_bytes=result[0],
                response_format=fmt,
                media_type=result[1],
                model_id=resolved_model,
                voice=voice,
            )
            done_extra = {"elapsed_seconds": round(elapsed, 3), "bytes": len(result[0])}
            if saved_path is not None:
                done_extra["output_path"] = str(saved_path)
            self.finish_request(request_id, "done", **done_extra)
            return result
        except HTTPException as exc:
            self.inc_stat("requests_error")
            status = "cancelled" if exc.status_code == 499 else "error"
            self.finish_request(request_id, status, error=str(exc.detail), status_code=exc.status_code)
            raise
        except Exception as exc:
            self.inc_stat("requests_error")
            status = "timeout" if isinstance(exc, asyncio.TimeoutError) else "error"
            self.finish_request(request_id, status, error=str(exc))
            raise

    def as_service_extras_kwargs(self) -> dict[str, Callable | object]:
        return {
            "tts_cache": self.tts_cache,
            "active_requests": self.active_requests,
            "stats": self.stats,
            "synthesize_threaded": self.synthesize_response_threaded,
            "new_request_id": self.new_request_id,
            "normalize_response_format": self.normalize_response_format,
            "mark_request": self.mark_request,
            "finish_request": self.finish_request,
            "increment_stat": self.inc_stat,
            "cache_clear": self.cache_clear,
            "cache_size": self.cache_size,
        }
