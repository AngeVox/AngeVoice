"""Runtime resource, idle restart, and output file state."""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from ...audio_formats import normalize_response_format as normalize_public_audio_format

logger = logging.getLogger(__name__)


class ResourceStateMixin:
    def idle_restart_snapshot(self) -> dict:
        """返回空闲卸载后彻底清理的运行状态。"""
        with self._idle_restart_lock:
            return {
                "enabled": bool(getattr(self.cfg, "restart_after_idle_unload_enabled", False)),
                "scheduled": bool(self._idle_restart_scheduled),
                "last_plan_at": self._last_idle_restart_plan_at or None,
                "delay_seconds": float(getattr(self.cfg, "restart_after_idle_unload_delay_seconds", 3.0) or 0.0),
                "cooldown_seconds": float(getattr(self.cfg, "restart_after_idle_unload_cooldown_seconds", 1800.0) or 0.0),
                "exit_code": int(getattr(self.cfg, "restart_after_idle_unload_exit_code", 75) or 0),
                "reason": self._idle_restart_reason,
                "models": list(self._idle_restart_models),
            }

    def handle_idle_unload_completed(self, unloaded_models: list[str]) -> None:
        """模型因空闲卸载完成后，按配置安排一次彻底清理。"""
        self.handle_model_unload_completed(unloaded_models, reason="idle")

    def handle_model_unload_completed(self, unloaded_models: list[str], *, reason: str = "manual") -> dict:
        """模型卸载完成后，在服务真正空闲时安排容器级重启。"""
        if not unloaded_models or not bool(getattr(self.cfg, "restart_after_idle_unload_enabled", False)):
            return self.idle_restart_snapshot()
        if not self._idle_restart_safe():
            logger.info("模型释放后暂不彻底清理：服务仍有活跃请求、连接或已加载模型")
            return self.idle_restart_snapshot()
        self._schedule_idle_restart(unloaded_models, reason=reason)
        return self.idle_restart_snapshot()

    def _idle_restart_safe(self) -> bool:
        """确认当前没有用户请求、WebSocket 连接或已加载模型。"""
        if self.active_websocket_connections > 0:
            return False
        with self.request_lock:
            active_statuses = {"queued", "running", "streaming", "loading", "processing", "cancelling"}
            if any(str(item.get("status", "")).lower() in active_statuses for item in self.active_requests.values()):
                return False
        try:
            models = self.model_manager.list_models()
        except Exception:
            logger.debug("读取模型快照失败，取消本次空闲彻底清理", exc_info=True)
            return False
        return not any(bool(model.get("loaded")) for model in models)

    def _schedule_idle_restart(self, unloaded_models: list[str], *, reason: str) -> None:
        delay = max(0.0, float(getattr(self.cfg, "restart_after_idle_unload_delay_seconds", 3.0) or 0.0))
        cooldown = max(0.0, float(getattr(self.cfg, "restart_after_idle_unload_cooldown_seconds", 1800.0) or 0.0))
        now = time.monotonic()
        with self._idle_restart_lock:
            if self._idle_restart_scheduled:
                return
            if cooldown > 0 and self._last_idle_restart_plan_at and now - self._last_idle_restart_plan_at < cooldown:
                logger.info("空闲彻底清理仍在冷却期，跳过本次退出计划")
                return
            self._idle_restart_scheduled = True
            self._last_idle_restart_plan_at = now
            self._idle_restart_reason = str(reason or "manual")
            self._idle_restart_models = list(unloaded_models)
        logger.warning(
            "模型 %s 已释放（原因：%s），%.1fs 后将退出进程以彻底释放运行时资源",
            ", ".join(unloaded_models),
            self._idle_restart_reason,
            delay,
        )
        timer = self._timer_factory(delay, self._perform_idle_restart, args=(list(unloaded_models), self._idle_restart_reason))
        timer.daemon = True
        timer.start()

    def _perform_idle_restart(self, unloaded_models: list[str], reason: str) -> None:
        if not self._idle_restart_safe():
            with self._idle_restart_lock:
                self._idle_restart_scheduled = False
                self._idle_restart_reason = ""
                self._idle_restart_models = []
            logger.info("空闲彻底清理已取消：退出前检测到新请求、连接或已加载模型")
            return
        exit_code = int(getattr(self.cfg, "restart_after_idle_unload_exit_code", 75) or 0)
        logger.warning(
            "模型 %s 释放后服务仍为空闲（原因：%s），正在退出进程以交给容器或服务管理器自动拉起（exit_code=%d）",
            ", ".join(unloaded_models),
            reason,
            exit_code,
        )
        self._process_exit(exit_code)

    def rss_bytes(self) -> int | None:
        return self.runtime_resources.rss_bytes()

    def resource_snapshot(self) -> dict:
        return self.runtime_resources.snapshot()

    def release_resources(self, *, clear_cache: bool = True, unload_models: bool = False, include_current: bool = True) -> dict:
        return self.runtime_resources.release(clear_cache=clear_cache, unload_models=unload_models, include_current=include_current)

    def normalize_response_format(self, fmt: str) -> str:
        return normalize_public_audio_format(fmt, self.cfg)

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
        elif media_type == "audio/ogg" or fmt == "ogg_opus":
            ext = "ogg"
        elif media_type == "audio/mp4" or fmt == "m4a":
            ext = "m4a"
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
            if item.is_file() and item.suffix.lower() in {".wav", ".mp3", ".ogg", ".m4a", ".pcm_s16le"}
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

