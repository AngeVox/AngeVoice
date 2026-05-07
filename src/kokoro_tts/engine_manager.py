"""Runtime model selection for AngeVoice."""

from __future__ import annotations

import importlib.util
import logging
import sys
import threading
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
    """Owns lazily loaded engines and coordinates exclusive model switching."""

    def __init__(self, cfg: TTSConfig, initial_engine=None):
        self.cfg = cfg
        self._lock = threading.RLock()
        self._engines: dict[str, object] = {}
        self._current_model_id = self.normalize_model_id(cfg.default_model)
        if initial_engine is not None:
            self._engines["kokoro"] = initial_engine
            self._current_model_id = "kokoro"

    @property
    def current_model_id(self) -> str:
        return self._current_model_id

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
                logger.warning("Ignoring unknown AngeVoice model id: %s", item)
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
        unload_previous = self.cfg.model_unload_on_switch if unload_previous is None else bool(unload_previous)
        with self._lock:
            previous_id = self._current_model_id
            unloaded_previous = False
            if unload_previous and previous_id != target_id:
                unloaded_previous = self.unload_model(previous_id)
            try:
                engine = self.get_engine(target_id, load=load)
            except Exception:
                self._current_model_id = previous_id
                if unloaded_previous:
                    try:
                        self.get_engine(previous_id, load=True)
                    except Exception:
                        logger.exception("Failed to restore previous model after switching to %s failed", target_id)
                raise
            self._current_model_id = target_id
            return {
                "ok": True,
                "previous_model": previous_id,
                "current_model": target_id,
                "unloaded_previous": unloaded_previous,
                "model": self._engine_metadata(engine) or self._model_snapshot(self._spec_for(target_id)),
            }

    @contextmanager
    def borrow(self, model_id: str | None = None) -> Iterator[object]:
        target_id = self.normalize_model_id(model_id)
        self._ensure_enabled(target_id)
        with self._lock:
            if target_id != self._current_model_id and self.cfg.model_unload_on_switch:
                self.switch_model(target_id, unload_previous=True, load=True)
            engine = self.get_engine(target_id, load=True)
            yield engine

    def get_engine(self, model_id: str | None = None, *, load: bool = True):
        target_id = self.normalize_model_id(model_id)
        self._ensure_enabled(target_id)
        engine = self._engines.get(target_id)
        if engine is None:
            engine = self._create_engine(target_id)
            self._engines[target_id] = engine
        if load and not bool(getattr(engine, "is_loaded", False)):
            engine.load()
        return engine

    def unload_model(self, model_id: str) -> bool:
        target_id = self.normalize_model_id(model_id)
        engine = self._engines.get(target_id)
        if engine is None:
            return False
        unload = getattr(engine, "unload", None)
        if callable(unload):
            unload()
        return True

    def unload_inactive(self) -> list[str]:
        unloaded: list[str] = []
        with self._lock:
            for model_id in list(self._engines):
                if model_id == self._current_model_id:
                    continue
                if self.unload_model(model_id):
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
        runtime = self._engine_metadata(engine) if loaded and engine is not None else {}
        static_capabilities = self._static_capabilities(spec)
        return {
            "id": spec.id,
            "name": spec.name,
            "backend": spec.backend,
            "provider": spec.provider,
            "experimental": spec.experimental,
            "enabled": True,
            "current": spec.id == self._current_model_id,
            "loaded": loaded,
            "available": self._runtime_available(spec),
            **static_capabilities,
            **runtime,
        }

    def _static_capabilities(self, spec: EngineSpec) -> dict:
        if spec.backend != "moss-tts-nano-onnx":
            return {
                "modes": ["preset_voice"],
                "voice_clone_supported": False,
                "speed_supported": True,
                "text_rules_enabled": True,
            }
        return {
            "modes": ["preset_voice", "voice_clone"],
            "voice_clone_supported": True,
            "voice_clone_enabled": True,
            "default_voice": self.cfg.moss_default_voice,
            "speed_supported": False,
            "text_rules_enabled": bool(self.cfg.moss_apply_angevoice_rules),
            "sample_rate": 48000,
            "channels": 2,
        }

    def _engine_metadata(self, engine) -> dict:
        metadata = getattr(engine, "metadata", None)
        if not callable(metadata):
            return {}
        try:
            value = metadata()
        except Exception:
            logger.debug("Engine metadata failed", exc_info=True)
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
