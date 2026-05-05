"""Runtime state and shared service helpers for AngeVoice."""

import asyncio
import hashlib
import logging
import threading
import time
import uuid
from collections import OrderedDict
from typing import Callable

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool

from .config import TTSConfig
from .engine import TTSEngine

logger = logging.getLogger(__name__)


class ServiceState:
    """Mutable runtime state for one AngeVoice FastAPI application."""

    def __init__(self, cfg: TTSConfig, eng: TTSEngine):
        self.cfg = cfg
        self.eng = eng
        self.tts_semaphore = asyncio.Semaphore(max(1, int(cfg.max_concurrent_requests)))
        self.tts_cache: OrderedDict[str, tuple[bytes, str]] = OrderedDict()
        self.active_requests: dict[str, dict] = {}
        self.cancelled_requests: set[str] = set()
        self.stats_lock = threading.Lock()
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

    def cache_key(self, text: str, voice: str, speed: float, fmt: str) -> str:
        payload = f"{voice}\0{float(speed):.3f}\0{fmt}\0{text}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def cache_get(self, key: str):
        if not self.cfg.cache_enabled or self.cfg.cache_max_items <= 0:
            return None
        item = self.tts_cache.get(key)
        if item is None:
            self.inc_stat("cache_misses")
            return None
        self.tts_cache.move_to_end(key)
        self.inc_stat("cache_hits")
        return item

    def cache_set(self, key: str, value: tuple[bytes, str]) -> None:
        if not self.cfg.cache_enabled or self.cfg.cache_max_items <= 0:
            return
        self.tts_cache[key] = value
        self.tts_cache.move_to_end(key)
        while len(self.tts_cache) > self.cfg.cache_max_items:
            self.tts_cache.popitem(last=False)

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

    def synthesize_response_bytes(self, text: str, voice: str, speed: float, fmt: str) -> tuple[bytes, str]:
        fmt = self.normalize_response_format(fmt)
        key = self.cache_key(text, voice, speed, fmt)
        cached = self.cache_get(key)
        if cached is not None:
            return cached

        if fmt == "pcm":
            wav = self.eng.synthesize_array(text=text, voice=voice, speed=speed)
            result = (self.eng._encode_segment(wav, "pcm_s16le"), "audio/pcm")
        elif fmt == "mp3":
            from .service_extras import _wav_to_mp3
            wav_bytes = self.eng.synthesize(text=text, voice=voice, speed=speed)
            result = (_wav_to_mp3(wav_bytes, getattr(self.cfg, "mp3_bitrate", "192k")), "audio/mpeg")
        else:
            result = (self.eng.synthesize(text=text, voice=voice, speed=speed), "audio/wav")
        self.cache_set(key, result)
        return result

    async def synthesize_response_threaded(self, text: str, voice: str, speed: float, fmt: str, request_id: str):
        start = time.perf_counter()
        self.inc_stat("requests_total")
        self.inc_stat("characters_total", len(text or ""))
        self.mark_request(request_id, "queued", voice=voice, format=fmt, chars=len(text or ""))
        try:
            async with self.tts_semaphore:
                if self.is_cancelled(request_id):
                    self.finish_request(request_id, "cancelled")
                    raise HTTPException(status_code=499, detail="Request cancelled")
                self.mark_request(request_id, "running")
                result = await asyncio.wait_for(
                    run_in_threadpool(self.synthesize_response_bytes, text, voice, speed, fmt),
                    timeout=self.cfg.request_timeout_seconds,
                )
            elapsed = time.perf_counter() - start
            self.inc_stat("requests_ok")
            self.inc_stat("audio_bytes_total", len(result[0]))
            self.inc_stat("synthesis_seconds_total", elapsed)
            self.finish_request(request_id, "done", elapsed_seconds=round(elapsed, 3), bytes=len(result[0]))
            return result
        except HTTPException:
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
        }
