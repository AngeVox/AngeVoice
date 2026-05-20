"""AngeVoice 运行时模型选择与生命周期管理。"""

from __future__ import annotations

import importlib.util
import logging
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from fastapi import HTTPException

from .config import TTSConfig
from .engine import TTSEngine
from .moss_engine import MossNanoEngine

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EngineSpec:
    id: str
    name: str
    backend: str
    provider: str
    experimental: bool = False


def _normalize_moss_id(provider: str) -> str:
    provider = str(provider or "cpu").strip().lower()
    return "moss-nano-cuda" if provider == "cuda" else "moss-nano-cpu"


class EngineManager:
    """统一管理 Kokoro/MOSS 引擎的懒加载、切换与空闲释放。"""

    def __init__(self, cfg: TTSConfig, initial_engine=None):
        self.cfg = cfg
        self._lock = threading.RLock()
        self._engines: dict[str, object] = {}
        self._current_model_id = self.normalize_model_id(cfg.default_model)
        self._last_used: dict[str, float] = {}
        self._active_counts: dict[str, int] = {}
        self._pending_rebuild: set[str] = set()
        if initial_engine is not None:
            self._engines["kokoro"] = initial_engine
            self._current_model_id = "kokoro"
            self._last_used["kokoro"] = time.monotonic()
        self._idle_timer: threading.Timer | None = None
        self._idle_timer_stop = threading.Event()
        self._start_idle_timer()

    @property
    def current_model_id(self) -> str:
        return self._current_model_id

    def _touch_model(self, model_id: str) -> None:
        self._last_used[model_id] = time.monotonic()

    def _active_count(self, model_id: str) -> int:
        return int(self._active_counts.get(model_id, 0) or 0)

    def _start_idle_timer(self) -> None:
        timeout = float(getattr(self.cfg, "model_idle_timeout_seconds", 0) or 0)
        if timeout <= 0:
            return
        interval = max(5.0, float(getattr(self.cfg, "model_idle_check_interval", 30) or 30))
        unload_current = bool(getattr(self.cfg, "model_idle_unload_current", True))
        logger.info("空闲卸载已启用：闲置 %.0fs 后释放模型（检查间隔 %.0fs，释放当前模型=%s）", timeout, interval, unload_current)
        self._idle_timer_stop.clear()
        self._schedule_idle_check(interval)

    def _schedule_idle_check(self, interval: float) -> None:
        if self._idle_timer_stop.is_set():
            return
        self._idle_timer = threading.Timer(interval, self._run_idle_check, args=(interval,))
        self._idle_timer.daemon = True
        self._idle_timer.start()

    def _run_idle_check(self, interval: float) -> None:
        try:
            self._check_and_unload_idle_models()
        except Exception:
            logger.debug("空闲卸载检查失败", exc_info=True)
        finally:
            self._schedule_idle_check(interval)

    def _check_and_unload_idle_models(self) -> None:
        timeout = float(getattr(self.cfg, "model_idle_timeout_seconds", 0) or 0)
        if timeout <= 0:
            return
        now = time.monotonic()
        unloaded: list[str] = []
        unload_current = bool(getattr(self.cfg, "model_idle_unload_current", True))
        with self._lock:
            for model_id in list(self._engines.keys()):
                if model_id == self._current_model_id and not unload_current:
                    continue
                engine = self._engines.get(model_id)
                if engine is None or not getattr(engine, "is_loaded", False):
                    continue
                active = self._active_count(model_id)
                if active > 0:
                    logger.debug("跳过忙碌模型 %s：active_count=%d", model_id, active)
                    continue
                last = self._last_used.get(model_id, 0)
                idle_for = now - last
                if idle_for >= timeout and self.unload_model(model_id, force=False, raise_if_busy=False):
                    unloaded.append(model_id)
                    logger.info("空闲卸载：模型 %s 闲置 %.0fs 后已释放", model_id, idle_for)
        if unloaded:
            logger.info("空闲卸载完成：%s", ", ".join(unloaded))

    def stop_idle_timer(self) -> None:
        self._idle_timer_stop.set()
        if self._idle_timer is not None:
            self._idle_timer.cancel()
            self._idle_timer = None

    def normalize_model_id(self, model_id: str | None) -> str:
        raw = str(model_id or self._current_model_id or self.cfg.default_model).strip().lower()
        if raw in {"", "default", "current"}:
            return self._current_model_id
        if raw in {"kokoro", "kokoro-zh", "kokoro-v1.1", "kokoro-v1_1-zh", "tts-1", "tts-1-hd"}:
            return "kokoro"
        if raw in {"moss", "moss-nano", "moss-tts-nano"}:
            if self.cfg.moss_execution_provider == "cuda" and not self.cfg.moss_cuda_enabled:
                return "moss-nano-cpu"
            return _normalize_moss_id(self.cfg.moss_execution_provider)
        if raw in {"moss-cpu", "moss-nano-cpu", "moss-tts-nano-cpu"}:
            return "moss-nano-cpu"
        if raw in {"moss-cuda", "moss-gpu", "moss-nano-cuda", "moss-tts-nano-cuda"}:
            return "moss-nano-cuda"
        return raw

    def list_specs(self) -> list[EngineSpec]:
        specs: list[EngineSpec] = []
        seen: set[str] = set()
        for item in self.cfg.enabled_models:
            model_id = self.normalize_model_id(item)
            if model_id in seen:
                continue
            seen.add(model_id)
            if model_id == "kokoro":
                specs.append(EngineSpec("kokoro", "Kokoro v1.1 Chinese", "kokoro", self.cfg.device))
            elif model_id == "moss-nano-cpu":
                specs.append(EngineSpec(model_id, "MOSS-TTS-Nano CPU", "moss-tts-nano-onnx", "cpu"))
            elif model_id == "moss-nano-cuda":
                if not self.cfg.moss_cuda_enabled:
                    logger.info("MOSS CUDA model is disabled by MOSS_CUDA_ENABLED=false")
                    continue
                specs.append(EngineSpec(model_id, "MOSS-TTS-Nano CUDA", "moss-tts-nano-onnx", "cuda", experimental=True))
            else:
                logger.warning("忽略未知 AngeVoice 模型 ID：%s", item)
        if not specs:
            specs.append(EngineSpec("kokoro", "Kokoro v1.1 Chinese", "kokoro", self.cfg.device))
        return specs

    def list_models(self) -> list[dict]:
        specs = self.list_specs()
        with self._lock:
            return [self._model_snapshot(spec) for spec in specs]

    def current_snapshot(self) -> dict:
        spec = self._spec_for(self._current_model_id)
        with self._lock:
            return self._model_snapshot(spec)

    def switch_model(self, model_id: str, *, unload_previous: bool | None = None, load: bool = True) -> dict:
        target_id = self.normalize_model_id(model_id)
        self._ensure_enabled(target_id)
        self._touch_model(target_id)
        unload_previous = self.cfg.model_unload_on_switch if unload_previous is None else bool(unload_previous)
        with self._lock:
            previous_id = self._current_model_id
            unloaded_previous = False
            previous_busy = False
            if unload_previous and previous_id != target_id:
                previous_busy = self._active_count(previous_id) > 0
                if previous_busy:
                    logger.info("切换模型时保留忙碌旧模型：%s -> %s", previous_id, target_id)
                else:
                    unloaded_previous = self.unload_model(previous_id, force=False, raise_if_busy=False)
            try:
                engine = self.get_engine(target_id, load=load)
            except Exception:
                self._current_model_id = previous_id
                if unloaded_previous:
                    try:
                        self.get_engine(previous_id, load=True)
                    except Exception:
                        logger.exception("切换失败后恢复旧模型失败：%s", previous_id)
                raise
            self._current_model_id = target_id
            return {"ok": True, "previous_model": previous_id, "current_model": target_id, "unloaded_previous": unloaded_previous, "previous_busy": previous_busy, "model": self._engine_metadata(engine) or self._model_snapshot(self._spec_for(target_id))}

    @contextmanager
    def borrow(self, model_id: str | None = None) -> Iterator[object]:
        target_id = self.normalize_model_id(model_id)
        self._ensure_enabled(target_id)
        self._touch_model(target_id)
        with self._lock:
            if target_id != self._current_model_id and self.cfg.model_unload_on_switch:
                self.switch_model(target_id, unload_previous=True, load=True)
            engine = self.get_engine(target_id, load=True)
            if not bool(getattr(engine, "is_healthy", True)) or bool(getattr(engine, "_unhealthy", False)):
                logger.info("模型 %s 状态异常，准备重新加载", target_id)
                try:
                    engine.unload()
                    engine.load()
                except Exception:
                    logger.exception("重新加载模型失败：%s", target_id)
                    raise
            self._active_counts[target_id] = self._active_count(target_id) + 1
        try:
            yield engine
        finally:
            with self._lock:
                current = self._active_count(target_id)
                self._active_counts[target_id] = max(0, current - 1)
                self._touch_model(target_id)
                if self._active_counts[target_id] == 0 and target_id in self._pending_rebuild:
                    logger.info("模型 %s 请求结束，执行待重建", target_id)
                    self._pending_rebuild.discard(target_id)
                    try:
                        self.drop_model(target_id, force=True, raise_if_busy=False)
                    except Exception:
                        logger.debug("执行待重建失败：%s", target_id, exc_info=True)

    def get_engine(self, model_id: str | None = None, *, load: bool = True):
        target_id = self.normalize_model_id(model_id)
        self._ensure_enabled(target_id)
        engine = self._engines.get(target_id)
        if engine is None:
            engine = self._create_engine(target_id)
            self._engines[target_id] = engine
        if load and not bool(getattr(engine, "is_loaded", False)):
            try:
                engine.load()
            except Exception:
                # Loading failures (especially MOSS CUDA fallback/ORT allocation failures)
                # must not leave a half-initialized engine or stale busy state behind.
                self._active_counts[target_id] = 0
                unload = getattr(engine, "unload", None)
                if callable(unload):
                    try:
                        unload(force=True)
                    except TypeError:
                        unload()
                    except Exception:
                        logger.debug("加载失败后的模型清理失败：%s", target_id, exc_info=True)
                raise
            self._touch_model(target_id)
        return engine

    def unload_model(self, model_id: str, *, force: bool = False, raise_if_busy: bool = True) -> bool:
        target_id = self.normalize_model_id(model_id)
        with self._lock:
            active = self._active_count(target_id)
            if active > 0 and not force:
                message = f"Model {target_id} is busy: active_count={active}"
                if raise_if_busy:
                    raise HTTPException(status_code=409, detail=message)
                logger.info("跳过忙碌模型卸载：%s active_count=%d", target_id, active)
                return False
            engine = self._engines.get(target_id)
            if engine is None:
                return False
            unload = getattr(engine, "unload", None)
            if callable(unload):
                try:
                    unload(force=force)
                except TypeError:
                    unload()
            if force:
                self._active_counts[target_id] = 0
            return True


    def drop_model(self, model_id: str, *, force: bool = False, raise_if_busy: bool = True) -> bool:
        """Unload and remove an engine object so next load rebuilds it from current config."""
        target_id = self.normalize_model_id(model_id)
        with self._lock:
            active = self._active_count(target_id)
            if active > 0 and not force:
                message = f"Model {target_id} is busy: active_count={active}"
                if raise_if_busy:
                    raise HTTPException(status_code=409, detail=message)
                logger.info("跳过忙碌模型重建：%s active_count=%d，已标记为待重建", target_id, active)
                self._pending_rebuild.add(target_id)
                return False
            self._pending_rebuild.discard(target_id)
            engine = self._engines.pop(target_id, None)
            if engine is None:
                return False
            unload = getattr(engine, "unload", None)
            if callable(unload):
                try:
                    unload(force=force)
                except TypeError:
                    unload()
            if force:
                self._active_counts[target_id] = 0
            return True

    def drop_matching(self, predicate, *, force: bool = False) -> list[str]:
        """Drop all cached engine objects that match predicate(model_id)."""
        dropped: list[str] = []
        for model_id in list(self._engines):
            if predicate(model_id) and self.drop_model(model_id, force=force, raise_if_busy=False):
                dropped.append(model_id)
        return dropped

    def unload_inactive(self, *, force: bool = False, include_current: bool = True) -> list[str]:
        unloaded: list[str] = []
        with self._lock:
            for model_id in list(self._engines):
                if model_id == self._current_model_id and not include_current:
                    continue
                if self.unload_model(model_id, force=force, raise_if_busy=False):
                    unloaded.append(model_id)
        return unloaded

    def _create_engine(self, model_id: str):
        if model_id == "kokoro":
            return TTSEngine(self.cfg)
        if model_id == "moss-nano-cpu":
            return MossNanoEngine(self.cfg, execution_provider="cpu", engine_id=model_id)
        if model_id == "moss-nano-cuda":
            return MossNanoEngine(self.cfg, execution_provider="cuda", engine_id=model_id)
        raise HTTPException(status_code=404, detail=f"Unknown model: {model_id}")

    def _ensure_enabled(self, model_id: str) -> None:
        enabled = {spec.id for spec in self.list_specs()}
        if model_id not in enabled:
            raise HTTPException(status_code=404, detail=f"Model is not enabled: {model_id}")

    def _spec_for(self, model_id: str) -> EngineSpec:
        for spec in self.list_specs():
            if spec.id == model_id:
                return spec
        return EngineSpec(model_id, model_id, "unknown", "unknown")

    def _model_snapshot(self, spec: EngineSpec) -> dict:
        engine = self._engines.get(spec.id)
        loaded = bool(getattr(engine, "is_loaded", False)) if engine is not None else False
        healthy = bool(getattr(engine, "is_healthy", True)) if engine is not None else True
        runtime = self._engine_metadata(engine) if loaded and engine is not None else {}
        active_count = self._active_count(spec.id)
        idle_timeout = float(getattr(self.cfg, "model_idle_timeout_seconds", 0) or 0)
        idle_unloaded = bool(engine is not None and not loaded and idle_timeout > 0 and spec.id in self._last_used)
        return {"id": spec.id, "name": spec.name, "backend": spec.backend, "provider": spec.provider, "experimental": spec.experimental, "enabled": True, "current": spec.id == self._current_model_id, "loaded": loaded, "healthy": healthy, "available": self._runtime_available(spec), "active_count": active_count, "pending_rebuild": spec.id in self._pending_rebuild, "idle_timeout_seconds": idle_timeout, "idle_unload_current": bool(getattr(self.cfg, "model_idle_unload_current", True)), "idle_unloaded": idle_unloaded, **self._static_capabilities(spec), **runtime}

    def _static_capabilities(self, spec: EngineSpec) -> dict:
        if spec.backend != "moss-tts-nano-onnx":
            return {"modes": ["preset_voice"], "voice_clone_supported": False, "speed_supported": True, "text_rules_enabled": True}
        text_rules_mode = str(getattr(self.cfg, "moss_apply_angevoice_rules", "auto")).strip().lower()
        text_rules_enabled = text_rules_mode != "false"
        return {"modes": ["preset_voice", "voice_clone"], "voice_clone_supported": True, "voice_clone_enabled": True, "default_voice": self.cfg.moss_default_voice, "speed_supported": False, "text_rules_enabled": text_rules_enabled, "sample_rate": 48000, "channels": 2}

    def _engine_metadata(self, engine) -> dict:
        metadata = getattr(engine, "metadata", None)
        if not callable(metadata):
            return {}
        try:
            value = metadata()
        except Exception:
            logger.debug("读取模型元数据失败", exc_info=True)
            return {}
        return value if isinstance(value, dict) else {}

    def _runtime_available(self, spec: EngineSpec) -> bool:
        if spec.id == "kokoro":
            return True
        if spec.id == "moss-nano-cuda" and not self.cfg.moss_cuda_enabled:
            return False
        if spec.backend != "moss-tts-nano-onnx":
            return False
        repo_path = self.cfg.moss_repo_path
        if repo_path:
            candidate = Path(repo_path).expanduser().resolve() / "onnx_tts_runtime.py"
            if candidate.exists():
                return True
        return importlib.util.find_spec("onnx_tts_runtime") is not None or "onnx_tts_runtime" in sys.modules
