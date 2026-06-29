"""TTS response cache state."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class CacheStateMixin:
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
        payload = "\0".join(
            [model_id, voice, f"{float(speed):.3f}", fmt, prompt_audio_id, prompt_text_digest, profile_revision, controls, text]
        ).encode("utf-8")
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

