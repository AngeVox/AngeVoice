"""Unified model asset inspection and repair orchestration for AngeVoice deployments."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .kokoro_assets import has_valid_kokoro_local_assets
from .model_sources import (
    ensure_kokoro_model_dir,
    ensure_moss_audio_tokenizer_dir,
    ensure_moss_model_dir,
    has_valid_moss_audio_tokenizer_assets,
    has_valid_moss_model_assets,
)
from .zipvoice.assets import ZipVoiceAssetManager

logger = logging.getLogger(__name__)


class ModelAssetService:
    """Model-neutral view over local durable assets and repair operations."""

    def __init__(self, cfg):
        self.cfg = cfg
        cuda_manifest = Path(__file__).with_name("zipvoice") / "assets_manifest_cuda.json"
        requested = str(getattr(cfg, "zipvoice_execution_provider", "cpu") or "cpu").strip().lower()
        self.zipvoice = ZipVoiceAssetManager(cfg, manifest_path=cuda_manifest if requested == "cuda" else None)

    def status(self, *, full_verify_zipvoice: bool = False) -> dict[str, Any]:
        kokoro_dir = Path(self.cfg.model_dir).expanduser()
        moss_dir = Path(getattr(self.cfg, "moss_model_dir", None) or "/app/models/MOSS-TTS-Nano-100M-ONNX").expanduser()
        tokenizer_dir = Path(getattr(self.cfg, "moss_audio_tokenizer_model_dir", None) or "/app/models/MOSS-Audio-Tokenizer-Nano-ONNX").expanduser()
        models: dict[str, Any] = {
            "kokoro": {
                "engine": "kokoro",
                "path": str(kokoro_dir),
                "ready": has_valid_kokoro_local_assets(kokoro_dir, log=logger),
                "voice_count": len(self.cfg.get_voices()),
                "repair_supported": True,
            },
            "moss": {
                "engine": "moss",
                "path": str(moss_dir),
                "tokenizer_path": str(tokenizer_dir),
                "tts_assets_ready": has_valid_moss_model_assets(moss_dir, log=logger),
                "tokenizer_assets_ready": has_valid_moss_audio_tokenizer_assets(tokenizer_dir, log=logger),
                "repair_supported": True,
            },
            "zipvoice": self.zipvoice.status(full_verify=full_verify_zipvoice),
        }
        models["moss"]["ready"] = bool(models["moss"]["tts_assets_ready"] and models["moss"]["tokenizer_assets_ready"])
        enabled = {str(item) for item in getattr(self.cfg, "enabled_models", [])}
        required = {
            "kokoro" if "kokoro" in enabled else None,
            "moss" if any(item.startswith("moss") for item in enabled) else None,
            "zipvoice" if "zipvoice" in enabled else None,
        } - {None}
        return {
            "storage": {
                "models_root": str(Path(getattr(self.cfg, "zipvoice_model_root", "/app/models/zipvoice")).expanduser().parent),
                "prompts_root": str(Path(getattr(self.cfg, "zipvoice_profiles_dir", "/app/prompts/zipvoice")).expanduser().parent),
            },
            "enabled_required": sorted(required),
            "ready": all(bool(models[item].get("ready")) for item in required),
            "models": models,
        }

    def repair(self, model_id: str) -> dict[str, Any]:
        model_id = str(model_id or "").strip().lower()
        if model_id in {"moss-nano-cpu", "moss-nano-cuda"}:
            model_id = "moss"
        if model_id == "kokoro":
            path = ensure_kokoro_model_dir(self.cfg, logger=logger)
            return {"ok": bool(path and has_valid_kokoro_local_assets(Path(path), log=logger)), "model": model_id, "path": str(path or self.cfg.model_dir)}
        if model_id == "moss":
            model_path = ensure_moss_model_dir(self.cfg, logger=logger)
            tokenizer_path = ensure_moss_audio_tokenizer_dir(self.cfg, logger=logger)
            ok = has_valid_moss_model_assets(Path(model_path), log=logger) and has_valid_moss_audio_tokenizer_assets(Path(tokenizer_path), log=logger)
            return {"ok": bool(ok), "model": model_id, "path": str(model_path), "tokenizer_path": str(tokenizer_path)}
        if model_id == "zipvoice":
            result = self.zipvoice.ensure()
            return {"ok": bool(result.get("ready")), "model": model_id, "assets": result}
        raise ValueError(f"不支持的模型资产修复目标: {model_id}")
