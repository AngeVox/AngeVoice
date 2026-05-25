"""AngeVoice 运行时模型选择与生命周期管理。"""

from __future__ import annotations

import importlib.util
import logging
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator

from fastapi import HTTPException

from .config import TTSConfig
from .engine import TTSEngine
from .moss_engine import MossNanoEngine
from .engines import EngineRegistry, EngineSpec

if TYPE_CHECKING:
    from .zipvoice.engine import ZipVoiceEngine

logger = logging.getLogger(__name__)


class EngineManager:
    """统一管理 Kokoro/MOSS/ZipVoice 引擎的懒加载、切换与空闲释放。"""

    def __init__(self, cfg: TTSConfig, initial_engine=None):
        self.cfg = cfg
        self.registry = EngineRegistry()
        self._voice_profile_service = None
        # Lifecycle transitions intentionally re-enter public helpers while the
        # rollback boundary is held (switch -> load/unload/drop).  RLock keeps
        # that transaction atomic; replacing it with Lock would deadlock.
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

    def bind_voice_profile_service(self, service) -> None:
        """Bind the single profile owner used by profile-capable adapters."""
        with self._lock:
            self._voice_profile_service = service
            existing = self._engines.get("zipvoice")
            if existing is not None and hasattr(existing, "profiles") and service.supports_profiles("zipvoice"):
                existing.profiles = service.store_for("zipvoice")

    def _touch_model(self, model_id: str) -> None:
        with self._lock:
            self._last_used[model_id] = time.monotonic()

    def _active_count(self, model_id: str) -> int:
        with self._lock:
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

    def resolve_model_id(self, model_id: str | None):
        """Resolve public and legacy model identifiers to one canonical product ID."""
        default_id = getattr(self, "_current_model_id", "") or self.cfg.default_model or "kokoro"
        return self.registry.resolve(model_id, default_id=default_id)

    def normalize_model_id(self, model_id: str | None) -> str:
        return self.resolve_model_id(model_id).canonical_id

    def list_specs(self) -> list[EngineSpec]:
        """Return only product-level models suitable for public UI/catalog APIs."""
        return self.registry.list_specs(self.cfg)

    def list_models(self) -> list[dict]:
        specs = self.list_specs()
        with self._lock:
            return [self._model_snapshot(spec) for spec in specs]

    def current_snapshot(self) -> dict:
        spec = self._spec_for(self._current_model_id)
        with self._lock:
            return self._model_snapshot(spec)

    def switch_model(self, model_id: str, *, unload_previous: bool | None = None, load: bool = True) -> dict[str, Any]:
        resolution = self.resolve_model_id(model_id)
        target_id = resolution.canonical_id
        self._ensure_resolution_enabled(resolution)
        unload_previous = self.cfg.model_unload_on_switch if unload_previous is None else bool(unload_previous)
        with self._lock:
            self._touch_model(target_id)
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
                engine = self.get_engine(target_id, load=load, provider_hint=resolution.provider_hint)
            except Exception:
                self._current_model_id = previous_id
                if unloaded_previous:
                    try:
                        self.get_engine(previous_id, load=True)
                    except Exception:
                        logger.exception("切换失败后恢复旧模型失败：%s", previous_id)
                raise
            self._current_model_id = target_id
            model_snapshot = self._engine_metadata(engine) or self._model_snapshot(self._spec_for(target_id))
            return {
                "ok": True,
                "previous_model": previous_id,
                "current_model": target_id,
                "unloaded_previous": unloaded_previous,
                "previous_busy": previous_busy,
                "requested_model": resolution.original_id,
                "canonical_model": target_id,
                "deprecated_alias": resolution.deprecated_alias,
                "provider_hint": resolution.provider_hint,
                "model": model_snapshot,
            }

    @contextmanager
    def borrow(self, model_id: str | None = None) -> Iterator[TTSEngine | MossNanoEngine | "ZipVoiceEngine"]:
        resolution = self.resolve_model_id(model_id)
        target_id = resolution.canonical_id
        self._ensure_resolution_enabled(resolution)
        # Keep switch/load/active-count registration atomic. switch_model and
        # get_engine may re-enter the deliberate RLock above.
        with self._lock:
            self._touch_model(target_id)
            if target_id != self._current_model_id and self.cfg.model_unload_on_switch:
                self.switch_model(model_id or target_id, unload_previous=True, load=True)
            engine = self.get_engine(target_id, load=True, provider_hint=resolution.provider_hint)
            if getattr(engine, "is_healthy", True) is False:
                logger.info("模型 %s 状态异常，丢弃旧实例并创建干净的新实例", target_id)
                try:
                    self.drop_model(target_id, force=True, raise_if_busy=False)
                    engine = self.get_engine(target_id, load=True, provider_hint=resolution.provider_hint)
                except Exception:
                    logger.exception("替换异常模型失败：%s", target_id)
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
                        self._pending_rebuild.add(target_id)
                        logger.warning("执行待重建失败，保留待重建标记：%s", target_id, exc_info=True)

    def _unload_other_loaded_models(self, target_id: str) -> None:
        """Keep one warm runtime by default to protect NAS RAM/VRAM budgets."""
        for model_id, other in list(self._engines.items()):
            if model_id == target_id or not bool(getattr(other, "is_loaded", False)):
                continue
            if self._active_count(model_id) > 0:
                raise HTTPException(status_code=409, detail=f"Model {model_id} is busy; cannot wake {target_id} yet")
            self.unload_model(model_id, force=False, raise_if_busy=False)

    def get_engine(self, model_id: str | None = None, *, load: bool = True, provider_hint: str | None = None):
        resolution = self.resolve_model_id(model_id)
        target_id = resolution.canonical_id
        effective_provider_hint = provider_hint or resolution.provider_hint
        self._ensure_resolution_enabled(resolution)
        with self._lock:
            engine = self._engines.get(target_id)
            needs_load = bool(load and (engine is None or not bool(getattr(engine, "is_loaded", False))))
            unloaded_for_target = False
            if needs_load:
                self._unload_other_loaded_models(target_id)
                unloaded_for_target = True
            if engine is not None and target_id == "moss" and effective_provider_hint:
                current_provider = str(getattr(engine, "requested_provider", "") or "").strip().lower()
                if current_provider and current_provider != effective_provider_hint:
                    if self._active_count(target_id) > 0:
                        raise HTTPException(status_code=409, detail="MOSS provider switch is busy")
                    self.drop_model(target_id, force=False, raise_if_busy=True)
                    engine = None
                    needs_load = bool(load)
            if needs_load and engine is None and not unloaded_for_target:
                self._unload_other_loaded_models(target_id)

            if engine is not None and (getattr(engine, "is_healthy", True) is False):
                logger.info("丢弃异常模型实例后重新创建：%s", target_id)
                self.drop_model(target_id, force=True, raise_if_busy=False)
                engine = None
            if engine is None:
                engine = self._create_engine(target_id, provider_hint=effective_provider_hint)
                self._engines[target_id] = engine
            if load and not bool(getattr(engine, "is_loaded", False)):
                try:
                    engine.load()
                except Exception:
                    # 加载失败不能留下半初始化引擎，也不能留下过期忙碌计数。
                    self._active_counts[target_id] = 0
                    unload = getattr(engine, "unload", None)
                    if callable(unload):
                        try:
                            unload(force=True)
                        except TypeError:
                            try:
                                unload()
                            except Exception:
                                logger.debug("加载失败后的模型清理失败：%s", target_id, exc_info=True)
                        except Exception:
                            logger.debug("加载失败后的模型清理失败：%s", target_id, exc_info=True)
                    self._engines.pop(target_id, None)
                    raise
                self._touch_model(target_id)
            return engine

    def warm_model(self, model_id: str, *, provider_hint: str | None = None) -> dict[str, Any]:
        """Load a model into memory without changing the selected runtime model."""
        resolution = self.resolve_model_id(model_id)
        target_id = resolution.canonical_id
        self._ensure_resolution_enabled(resolution)
        engine = self.get_engine(
            target_id,
            load=True,
            provider_hint=provider_hint or resolution.provider_hint,
        )
        return self._engine_metadata(engine)

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
                    try:
                        unload()
                    except Exception:
                        logger.warning("模型卸载失败：%s", target_id, exc_info=True)
                        return False
                except Exception:
                    logger.warning("模型卸载失败：%s", target_id, exc_info=True)
                    return False
            if force:
                self._active_counts[target_id] = 0
            return True


    def drop_model(self, model_id: str, *, force: bool = False, raise_if_busy: bool = True) -> bool:
        """卸载并移除引擎对象，让下次加载使用当前配置重新构建。"""
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
            engine = self._engines.get(target_id)
            if engine is None:
                self._pending_rebuild.discard(target_id)
                return False
            unload = getattr(engine, "unload", None)
            if callable(unload):
                try:
                    unload(force=force)
                except TypeError:
                    try:
                        unload()
                    except Exception:
                        logger.warning("模型重建前卸载失败：%s", target_id, exc_info=True)
                        self._pending_rebuild.add(target_id)
                        return False
                except Exception:
                    logger.warning("模型重建前卸载失败：%s", target_id, exc_info=True)
                    self._pending_rebuild.add(target_id)
                    return False
            self._pending_rebuild.discard(target_id)
            self._engines.pop(target_id, None)
            if force:
                self._active_counts[target_id] = 0
            return True

    def drop_matching(self, predicate, *, force: bool = False) -> list[str]:
        """移除所有符合 predicate(model_id) 的缓存引擎对象。"""
        dropped: list[str] = []
        with self._lock:
            model_ids = list(self._engines)
        for model_id in model_ids:
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

    def _create_engine(self, model_id: str, *, provider_hint: str | None = None):
        profile_store = None
        if self._voice_profile_service is not None and self._voice_profile_service.supports_profiles(model_id):
            profile_store = self._voice_profile_service.store_for(model_id)
        return self.registry.create_engine(model_id, self.cfg, provider_hint=provider_hint, voice_profile_store=profile_store)

    def _ensure_enabled(self, model_id: str) -> None:
        enabled = {spec.id for spec in self.list_specs()}
        if model_id not in enabled:
            raise HTTPException(status_code=404, detail=f"Model is not enabled: {model_id}")

    def _ensure_resolution_enabled(self, resolution) -> None:
        """Keep legacy provider aliases compatible without silently enabling another provider."""
        self._ensure_enabled(resolution.canonical_id)
        if resolution.canonical_id != "moss" or not resolution.provider_hint:
            return
        enabled_hints = {
            item.provider_hint
            for configured in self.cfg.enabled_models
            for item in [self.registry.resolve(configured, default_id=self.cfg.default_model)]
            if item.canonical_id == "moss" and item.provider_hint
        }
        if resolution.provider_hint == "cuda" and not bool(getattr(self.cfg, "moss_cuda_enabled", True)):
            raise HTTPException(status_code=404, detail="MOSS CUDA provider is disabled")
        if enabled_hints and resolution.provider_hint not in enabled_hints:
            raise HTTPException(status_code=404, detail=f"Legacy MOSS provider is not enabled: {resolution.original_id}; use model=moss")

    def _spec_for(self, model_id: str) -> EngineSpec:
        for spec in self.list_specs():
            if spec.id == model_id:
                return spec
        return EngineSpec(model_id, model_id, "unknown", "unknown")

    def _model_snapshot(self, spec: EngineSpec) -> dict[str, Any]:
        engine = self._engines.get(spec.id)
        loaded = bool(getattr(engine, "is_loaded", False)) if engine is not None else False
        healthy = bool(getattr(engine, "is_healthy", True)) if engine is not None else True
        # Keep last runtime/provider metrics observable after idle/manual unload.
        # metadata() for product engines is side-effect free and does not reload weights.
        runtime = self._engine_metadata(engine) if engine is not None else {}
        active_count = self._active_count(spec.id)
        idle_timeout = float(getattr(self.cfg, "model_idle_timeout_seconds", 0) or 0)
        idle_unloaded = bool(engine is not None and not loaded and idle_timeout > 0 and spec.id in self._last_used)

        snapshot: dict[str, Any] = {
            "id": spec.id,
            "name": spec.name,
            "backend": spec.backend,
            "provider": spec.provider,
            "requested_provider": spec.provider,
            "actual_provider": spec.provider if loaded else None,
            "fallback": False,
            "fallback_reason": "",
            "experimental": spec.experimental,
            "enabled": True,
            "current": spec.id == self._current_model_id,
            "loaded": loaded,
            "healthy": healthy,
            "available": self._runtime_available(spec),
            "active_count": active_count,
            "pending_rebuild": spec.id in self._pending_rebuild,
            "idle_timeout_seconds": idle_timeout,
            "idle_unload_current": bool(getattr(self.cfg, "model_idle_unload_current", True)),
            "idle_unloaded": idle_unloaded,
            "wakeable": True,
            "process_isolated": bool(getattr(self.cfg, f"{spec.id}_process_isolation_enabled", False)) if spec.id in {"kokoro", "moss", "zipvoice"} else False,
            "process_alive": False,
            "worker_pid": None,
            "release_guarantee": "worker_exit" if bool(getattr(self.cfg, f"{spec.id}_process_isolation_enabled", False)) else "in_process_best_effort",
            "last_generation_seconds": None,
            "last_audio_seconds": None,
            "last_rtf": None,
        }

        # 静态能力字段先合入，运行时 metadata 再合入。运行时字段允许覆盖
        # loaded/device/voices 等动态值，但基础 id/name/backend 不应被静默改写。
        snapshot.update(self._static_capabilities(spec))
        snapshot["parameter_schema"] = self.registry.parameter_schema_for(spec.id)
        snapshot["provider_policy"] = self.registry.provider_policy.as_dict(spec.id, spec.provider)
        protected_keys = {"id", "name", "backend", "provider", "experimental", "enabled"}
        runtime_metadata = {key: value for key, value in runtime.items() if key not in protected_keys}
        snapshot.update(runtime_metadata)
        snapshot.update(self.registry.provider_policy.status_from_snapshot(spec.provider, runtime, loaded=loaded).as_dict())
        return snapshot

    def _static_capabilities(self, spec: EngineSpec) -> dict[str, Any]:
        capabilities = self.registry.capabilities_for(spec, self.cfg).as_dict()
        if spec.id == "moss":
            capabilities["default_voice"] = self.cfg.moss_default_voice
        if spec.id == "zipvoice":
            capabilities["default_voice"] = ""
        return capabilities

    def _engine_metadata(self, engine) -> dict[str, Any]:
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
        if spec.id == "zipvoice":
            repo_path = getattr(self.cfg, "zipvoice_repo_path", None)
            if repo_path and (Path(repo_path).expanduser() / "zipvoice").is_dir():
                return True
            bundled = Path(__file__).resolve().parents[3] / "vendor" / "ZipVoice" / "zipvoice"
            return bundled.is_dir() or bool(getattr(self.cfg, "zipvoice_download_enabled", True))
        if spec.id == "moss" and spec.provider == "cuda" and not self.cfg.moss_cuda_enabled:
            return False
        if spec.backend != "moss-tts-nano-onnx":
            return False
        repo_path = self.cfg.moss_repo_path
        if repo_path:
            candidate = Path(repo_path).expanduser().resolve() / "onnx_tts_runtime.py"
            if candidate.exists():
                return True
        return importlib.util.find_spec("onnx_tts_runtime") is not None or "onnx_tts_runtime" in sys.modules
