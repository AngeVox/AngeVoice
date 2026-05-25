"""AngeVoice 运行状态与共用服务工具。"""

import asyncio
import hashlib
import json
import logging
import re
import threading
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Callable

from .latency_tracker import LatencyTracker

from fastapi import HTTPException

from .config import TTSConfig
from .engine import TTSEngine
from .engine_manager import EngineManager
from .engines.parameters import EngineParameterSchema
from .resources import RuntimeResourceService
from .services import StreamingService, SynthesisService, VoiceProfileService

logger = logging.getLogger(__name__)


class ServiceState:
    """单个 AngeVoice FastAPI 应用的可变运行状态。"""

    def __init__(self, cfg: TTSConfig, eng: TTSEngine | None = None, model_manager: EngineManager | None = None):
        self.cfg = cfg
        self.model_manager = model_manager or EngineManager(cfg, initial_engine=eng)
        self.parameter_schema = getattr(self.model_manager.registry, "parameter_schema", EngineParameterSchema())
        self.voice_profiles = VoiceProfileService(cfg)
        self.zipvoice_profiles = self.voice_profiles.store_for("zipvoice")  # legacy compatibility alias
        self.model_manager.bind_voice_profile_service(self.voice_profiles)
        self.eng = eng or self.model_manager.get_engine(self.model_manager.current_model_id, load=False)
        self.tts_semaphore = asyncio.Semaphore(max(1, int(cfg.max_concurrent_requests)))
        self._websocket_connections = 0
        self._websocket_connection_lock = asyncio.Lock()
        self.tts_cache: OrderedDict[str, tuple[bytes, str]] = OrderedDict()
        self._cache_bytes = 0
        self.cache_lock = threading.Lock()
        self.active_requests: dict[str, dict] = {}
        self.cancelled_requests: set[str] = set()
        self.stats_lock = threading.Lock()
        self.output_lock = threading.Lock()
        self.request_lock = threading.Lock()
        self.latency_tracker = LatencyTracker()
        self.stats = {
            "requests_total": 0,
            "requests_ok": 0,
            "requests_error": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "cache_skips": 0,
            "characters_total": 0,
            "audio_bytes_total": 0,
            "synthesis_seconds_total": 0.0,
            "ws_cancelled_total": 0,
            "ws_connections_rejected_total": 0,
            "ws_connections_peak": 0,
            "outputs_saved_total": 0,
            "started_at": time.time(),
        }
        self.runtime_resources = RuntimeResourceService(self)
        self.synthesis = SynthesisService(self)
        self.streaming = StreamingService(self)

    def inc_stat(self, name: str, delta=1) -> None:
        with self.stats_lock:
            self.stats[name] = self.stats.get(name, 0) + delta

    def snapshot_stats(self) -> dict:
        with self.stats_lock:
            snapshot = dict(self.stats)
        snapshot["ws_connections_active"] = self._websocket_connections
        return snapshot

    def new_request_id(self) -> str:
        return uuid.uuid4().hex[:12]

    async def try_acquire_websocket_connection(self) -> bool:
        """Reserve one WebSocket session slot before accepting the handshake."""
        limit = max(0, int(getattr(self.cfg, "websocket_max_connections", 0) or 0))
        async with self._websocket_connection_lock:
            if limit and self._websocket_connections >= limit:
                self.inc_stat("ws_connections_rejected_total")
                return False
            self._websocket_connections += 1
            with self.stats_lock:
                self.stats["ws_connections_peak"] = max(self.stats.get("ws_connections_peak", 0), self._websocket_connections)
            return True

    async def release_websocket_connection(self) -> None:
        async with self._websocket_connection_lock:
            self._websocket_connections = max(0, self._websocket_connections - 1)

    @property
    def active_websocket_connections(self) -> int:
        return self._websocket_connections

    def cache_key(
        self,
        model_id: str,
        text: str,
        voice: str,
        speed: float,
        fmt: str,
        prompt_audio_id: str = "",
        prompt_text: str = "",
        profile_revision: str = "",
        generation_params: dict | None = None,
    ) -> str:
        controls = json.dumps(generation_params or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        prompt_text_digest = hashlib.sha256(str(prompt_text or "").encode("utf-8")).hexdigest() if prompt_text else ""
        payload = "\0".join([model_id, voice, f"{float(speed):.3f}", fmt, prompt_audio_id, prompt_text_digest, profile_revision, controls, text]).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def prompt_audio_cache_id(self, model_id: str, prompt_audio_id: str = "") -> str:
        if prompt_audio_id:
            return str(prompt_audio_id)
        if not str(model_id or "").startswith("moss") or not self.cfg.moss_prompt_audio_path:
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
            logger.debug("读取引擎克隆能力元数据失败", exc_info=True)
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
        self.inc_stat("cache_hits" if item is not None else "cache_misses")
        return item

    def _cache_item_size(self, value: tuple[bytes, str]) -> int:
        try:
            return len(value[0])
        except Exception:
            return 0

    def _should_cache_result(self, *, text: str, value: tuple[bytes, str]) -> bool:
        if not self.cfg.cache_enabled or self.cfg.cache_max_items <= 0:
            return False
        text_limit = int(getattr(self.cfg, "cache_skip_text_over_chars", 0) or 0)
        if text_limit > 0 and len(text or "") > text_limit:
            self.inc_stat("cache_skips")
            return False
        audio_limit = int(getattr(self.cfg, "cache_skip_audio_over_bytes", 0) or 0)
        if audio_limit > 0 and self._cache_item_size(value) > audio_limit:
            self.inc_stat("cache_skips")
            return False
        return True

    def cache_set(self, key: str, value: tuple[bytes, str], *, text: str = "") -> None:
        if not self._should_cache_result(text=text, value=value):
            return
        item_size = self._cache_item_size(value)
        max_bytes = int(getattr(self.cfg, "cache_max_bytes", 0) or 0)
        with self.cache_lock:
            old = self.tts_cache.pop(key, None)
            if old is not None:
                self._cache_bytes = max(0, self._cache_bytes - self._cache_item_size(old))
            self.tts_cache[key] = value
            self._cache_bytes += item_size
            self.tts_cache.move_to_end(key)
            while len(self.tts_cache) > self.cfg.cache_max_items:
                _, removed = self.tts_cache.popitem(last=False)
                self._cache_bytes = max(0, self._cache_bytes - self._cache_item_size(removed))
            while max_bytes > 0 and self._cache_bytes > max_bytes and self.tts_cache:
                _, removed = self.tts_cache.popitem(last=False)
                self._cache_bytes = max(0, self._cache_bytes - self._cache_item_size(removed))

    def cache_size(self) -> int:
        with self.cache_lock:
            return len(self.tts_cache)

    def cache_bytes(self) -> int:
        with self.cache_lock:
            return int(self._cache_bytes)

    def cache_clear(self) -> int:
        with self.cache_lock:
            size = len(self.tts_cache)
            self.tts_cache.clear()
            self._cache_bytes = 0
            return size

    def rss_bytes(self) -> int | None:
        return self.runtime_resources.rss_bytes()

    def resource_snapshot(self) -> dict:
        return self.runtime_resources.snapshot()

    def release_resources(self, *, clear_cache: bool = True, unload_models: bool = False, include_current: bool = True) -> dict:
        return self.runtime_resources.release(clear_cache=clear_cache, unload_models=unload_models, include_current=include_current)

    def _zipvoice_prompt_context(self, model_id: str, voice: str, prompt_audio_path: str | None, prompt_audio_id: str, prompt_text: str) -> tuple[str | None, str, str, str]:
        """Compatibility proxy for legacy tests and older internal callers."""
        condition = self.voice_profiles.resolve_condition(
            model_id, voice, prompt_audio_path=prompt_audio_path, prompt_audio_id=prompt_audio_id, prompt_text=prompt_text
        )
        return condition.prompt_audio_path, condition.prompt_audio_id, condition.prompt_text, condition.revision

    def mark_request(self, request_id: str, status: str, **extra) -> None:
        if not self.cfg.queue_status_enabled:
            return
        with self.request_lock:
            item = self.active_requests.setdefault(
                request_id,
                {"id": request_id, "created_at": time.time(), "status": status},
            )
            item.update({"status": status, "updated_at": time.time(), **extra})

    def request_snapshot(self, *, limit: int | None = None, recent_first: bool = True) -> list[dict]:
        """Return a stable request snapshot without exposing the live shared mapping."""
        with self.request_lock:
            values = [dict(item) for item in self.active_requests.values()]
        values.sort(key=lambda item: float(item.get("updated_at", 0) or 0), reverse=recent_first)
        return values[:limit] if limit is not None else values

    def _prune_request_history(self, *, maximum: int = 100, remove_count: int = 20) -> None:
        """Prune completed history entries without removing running requests.

        The mapping is small and bounded, so selecting and removing entries under
        the same lock is preferable to a two-phase scan that can race with status
        updates from a concurrent synthesis request.
        """
        terminal = {"done", "error", "timeout", "cancelled"}
        with self.request_lock:
            if not self.cfg.queue_status_enabled or len(self.active_requests) <= maximum:
                return
            candidates = [
                (key, float(item.get("updated_at", 0) or 0))
                for key, item in self.active_requests.items()
                if item.get("status") in terminal
            ]
            for key, _updated_at in sorted(candidates, key=lambda pair: pair[1])[:remove_count]:
                self.active_requests.pop(key, None)

    def finish_request(self, request_id: str, status: str, **extra) -> None:
        self.mark_request(request_id, status, **extra)
        if status in {"done", "error", "timeout", "cancelled"}:
            with self.request_lock:
                self.cancelled_requests.discard(request_id)
        self._prune_request_history()

    def is_cancelled(self, request_id: str) -> bool:
        with self.request_lock:
            return request_id in self.cancelled_requests

    def request_cancel(self, request_id: str) -> bool:
        with self.request_lock:
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
            raise HTTPException(status_code=400, detail="MP3 输出未启用。如需使用，请启用 KOKORO_MP3_ENABLED 并安装 ffmpeg。")
        supported = "wav, pcm" + (", mp3" if getattr(self.cfg, "mp3_enabled", False) else "")
        raise HTTPException(status_code=400, detail=f"不支持的输出格式。当前支持：{supported}")

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
                logger.debug("清理过期输出文件失败：%s", item, exc_info=True)

    def synthesize_response_bytes(
        self,
        text: str,
        voice: str,
        speed: float,
        fmt: str,
        model_id: str | None = None,
        prompt_audio_path: str | None = None,
        prompt_audio_id: str = "",
        prompt_text: str = "",
        generation_params: dict | None = None,
    ) -> tuple[bytes, str]:
        request = self.synthesis.build_request(
            text=text, voice=voice, speed=speed, response_format=fmt, model_id=model_id,
            prompt_audio_path=prompt_audio_path, prompt_audio_id=prompt_audio_id, prompt_text=prompt_text,
            engine_params=generation_params,
        )
        return self.synthesis.response_bytes(request)

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
        prompt_text: str = "",
        generation_params: dict | None = None,
    ):
        request = self.synthesis.build_request(
            text=text, voice=voice, speed=speed, response_format=fmt, model_id=model_id,
            prompt_audio_path=prompt_audio_path, prompt_audio_id=prompt_audio_id, prompt_text=prompt_text,
            engine_params=generation_params, request_id=request_id,
        )
        return await self.synthesis.response_threaded(request)

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
