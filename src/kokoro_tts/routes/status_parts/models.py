"""Model catalog, voice list, and capability routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from ... import __version__
from ...audio_formats import supported_response_formats
from . import StatusRouteContext
from .health import auth_required, public_catalog_allowed_for_config


def guess_voice_gender(voice_id: str, model_id: str) -> str:
    """尽力推断音色性别，供阅读器 UI 使用。"""
    value = str(voice_id or "").strip().lower()
    if model_id == "kokoro":
        if value.startswith("zf") or "female" in value or "女" in value:
            return "female"
        if value.startswith("zm") or "male" in value or "男" in value:
            return "male"
    return "unknown"


def voice_display_name(voice_id: str, model_id: str) -> str:
    value = str(voice_id or "").strip()
    lower = value.lower()
    if model_id == "kokoro":
        suffix = value.split("_", 1)[1] if "_" in value else value
        if lower.startswith("zf"):
            return f"中文女声 {suffix}"
        if lower.startswith("zm"):
            return f"中文男声 {suffix}"
        return f"Kokoro {value}"
    if model_id.startswith("moss"):
        return f"MOSS {value}"
    return value


def role_hints_for_gender(gender: str) -> list[str]:
    if gender == "female":
        return ["female"]
    if gender == "male":
        return ["male"]
    return ["narrator", "unknown"]


def model_capabilities(snapshot: dict, cfg) -> dict:
    model_id = snapshot.get("id") or ""
    formats = supported_response_formats(cfg)
    supports_clone = bool(snapshot.get("voice_clone_supported") or snapshot.get("voice_clone_enabled"))
    return {
        "id": model_id,
        "name": snapshot.get("name") or model_id,
        "provider": "angevoice",
        "backend": snapshot.get("backend") or "unknown",
        "runtime_provider": snapshot.get("actual_provider") or snapshot.get("provider") or snapshot.get("device") or "unknown",
        "experimental": bool(snapshot.get("experimental", False)),
        "available": bool(snapshot.get("available", True)),
        "loaded": bool(snapshot.get("loaded", False)),
        "healthy": bool(snapshot.get("healthy", True)),
        "current": bool(snapshot.get("current", False)),
        "default_voice": snapshot.get("default_voice") or getattr(cfg, "default_voice", ""),
        "sample_rate": snapshot.get("sample_rate") or getattr(cfg, "sample_rate", 24000),
        "channels": snapshot.get("channels") or 1,
        "formats": formats,
        "supports_stream": bool(snapshot.get("streaming", getattr(cfg, "stream_enabled", False))),
        "supports_binary_stream": bool(getattr(cfg, "stream_binary_enabled", False)),
        "supports_batch": bool(getattr(cfg, "batch_enabled", False)),
        "supports_speed": bool(snapshot.get("speed_supported", False)),
        "supports_pitch": False,
        "supports_clone": supports_clone,
        "supports_saved_voice_profiles": bool(snapshot.get("supports_saved_voice_profiles", False)),
        "stream_mode": snapshot.get("stream_mode") or "segmented",
        "parameter_schema": snapshot.get("parameter_schema") or [],
        "provider_policy": snapshot.get("provider_policy") or {},
        "supports_emotion": False,
        "supports_style_prompt": False,
        "supports_ssml": False,
        "text_rules_enabled": bool(snapshot.get("text_rules_enabled", False)),
        "modes": snapshot.get("modes") or (["preset_voice", "voice_clone"] if supports_clone else ["preset_voice"]),
    }


def voice_details(model_id: str, voices: list[str], snapshot: dict, cfg) -> list[dict]:
    capabilities = model_capabilities(snapshot, cfg)
    return [
        {
            "id": str(voice),
            "name": str(voice),
            "display_name": voice_display_name(str(voice), model_id),
            "lang": "zh-CN",
            "locale": "zh-CN",
            "gender": guess_voice_gender(str(voice), model_id),
            "role_hints": role_hints_for_gender(guess_voice_gender(str(voice), model_id)),
            "provider": "angevoice",
            "backend": capabilities["backend"],
            "model": model_id,
            "supports_speed": capabilities["supports_speed"],
            "supports_clone": capabilities["supports_clone"],
            "supports_emotion": capabilities["supports_emotion"],
            "supports_style_prompt": capabilities["supports_style_prompt"],
            "formats": capabilities["formats"],
        }
        for voice in voices
    ]


def model_catalog_snapshot(ctx: StatusRouteContext, target_model: str) -> dict:
    """返回模型元数据和音色列表，不触发模型实际加载。"""
    state = ctx.state
    target_model = state.model_manager.normalize_model_id(target_model)
    snapshot = {}
    engine = None
    try:
        if target_model == state.model_manager.current_model_id:
            snapshot = state.model_manager.current_snapshot()
        else:
            snapshot = next((m for m in state.model_manager.list_models() if m.get("id") == target_model), {})
            engine = state.model_manager.get_engine(target_model, load=False)
            metadata = engine.metadata() if hasattr(engine, "metadata") and callable(engine.metadata) else {}
            if isinstance(metadata, dict):
                merged = dict(snapshot)
                merged.update(metadata)
                snapshot = merged
    except HTTPException:
        raise
    except Exception:
        snapshot = next((m for m in state.model_manager.list_models() if m.get("id") == target_model), {})
    snapshot.setdefault("id", target_model)
    voices = snapshot.get("voices") or []
    if not voices:
        try:
            if engine is None:
                engine = state.model_manager.get_engine(target_model, load=False)
            if hasattr(engine, "get_voices") and callable(engine.get_voices):
                voices = engine.get_voices()
        except Exception:
            voices = []
    if not isinstance(voices, list):
        voices = [str(voices)]
    snapshot["voices"] = [str(item) for item in voices]
    return snapshot


def attach_model_routes(router: APIRouter, ctx: StatusRouteContext) -> None:
    state = ctx.state
    cfg = ctx.cfg

    async def _verify_status_endpoint_access(request: Request):
        if getattr(cfg, "public_status_endpoints", True):
            return
        await ctx.verify_api_key(request)

    def _public_catalog_allowed() -> bool:
        return public_catalog_allowed_for_config(cfg)

    @router.get("/v1/audio/voices")
    async def list_voices(
        model: str | None = None,
        detail: bool = True,
        _=Depends(_verify_status_endpoint_access),
    ):
        target_model = state.model_manager.normalize_model_id(model)
        snapshot = model_catalog_snapshot(ctx, target_model)
        voices = snapshot.get("voices") or []
        response = {
            "model": target_model,
            "voices": voices,
            "count": len(voices),
            "default_voice": snapshot.get("default_voice") or cfg.default_voice,
            "capabilities": model_capabilities(snapshot, cfg),
        }
        if detail:
            response["voice_details"] = voice_details(target_model, voices, snapshot, cfg)
        return response

    @router.get("/v1/tts/capabilities")
    async def tts_capabilities(include_voices: bool = True, _=Depends(_verify_status_endpoint_access)):
        models = []
        for model in state.model_manager.list_models():
            model_id = str(model.get("id") or "")
            snapshot = model_catalog_snapshot(ctx, model_id)
            voices = snapshot.get("voices") or []
            item = model_capabilities(snapshot, cfg)
            item["voice_count"] = len(voices)
            if include_voices:
                item["voices"] = voice_details(model_id, voices, snapshot, cfg)
            models.append(item)
        formats = supported_response_formats(cfg)
        return {
            "service": "AngeVoice",
            "version": __version__,
            "current_model": state.model_manager.current_model_id,
            "auth_required": auth_required(cfg),
            "catalog_protected": not _public_catalog_allowed(),
            "formats": formats,
            "defaults": {
                "model": state.model_manager.current_model_id,
                "voice": cfg.default_voice,
                "speed": cfg.default_speed,
                "response_format": "wav",
            },
            "frontend_hints": {
                "preferred_response_encoding": "base64",
                "reader_role_types": ["narrator", "male", "female", "child", "unknown"],
                "emotion_fields_reserved": True,
            },
            "parameter_schemas": state.parameter_schema.schema_catalog(),
            "models": models,
        }

    @router.get("/v1/models")
    async def list_models(_=Depends(_verify_status_endpoint_access)):
        return {
            "current_model": state.model_manager.current_model_id,
            "enabled_models": list(getattr(cfg, "enabled_models", []) or []),
            "models": state.model_manager.list_models(),
        }

    @router.get("/v1/models/current")
    async def current_model(_=Depends(_verify_status_endpoint_access)):
        return state.model_manager.current_snapshot()

    @router.get("/v1/engines/parameter-schema")
    async def engine_parameter_schema(_=Depends(_verify_status_endpoint_access)):
        return {"schemas": state.parameter_schema.schema_catalog()}

