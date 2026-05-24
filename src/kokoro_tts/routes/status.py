"""状态、健康检查、音色列表和 Web UI 路由。"""

import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from .. import __version__
from ..service_state import ServiceState


def _get_vram_usage() -> dict:
    """返回 GPU 显存信息；不可用时返回状态说明。"""
    try:
        import torch  # noqa: F811
        if torch.cuda.is_available():
            device = torch.cuda.current_device()
            total = torch.cuda.get_device_properties(device).total_mem
            used = torch.cuda.memory_allocated(device)
            reserved = torch.cuda.memory_reserved(device)
            return {
                "available": True,
                "device_name": torch.cuda.get_device_name(device),
                "total_bytes": total,
                "used_bytes": used,
                "reserved_bytes": reserved,
                "free_bytes": total - reserved,
                "used_percent": round(used / total * 100, 1) if total > 0 else 0.0,
            }
        return {"available": False, "status": "no_cuda_device"}
    except ImportError:
        return {"available": False, "status": "torch_not_installed"}
    except Exception as exc:
        return {"available": False, "status": "error", "error": str(exc)}


def _guess_voice_gender(voice_id: str, model_id: str) -> str:
    """尽力推断音色性别，供阅读器 UI 使用。

    Kokoro 中文音色约定 zf_* 为女声、zm_* 为男声；
    MOSS 内置音色没有可靠的性别元数据，返回 unknown 更安全。
    """
    value = str(voice_id or "").strip().lower()
    if model_id == "kokoro":
        if value.startswith("zf") or "female" in value or "女" in value:
            return "female"
        if value.startswith("zm") or "male" in value or "男" in value:
            return "male"
    return "unknown"


def _voice_display_name(voice_id: str, model_id: str) -> str:
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


def _role_hints_for_gender(gender: str) -> list[str]:
    if gender == "female":
        return ["female"]
    if gender == "male":
        return ["male"]
    return ["narrator", "unknown"]


def _model_capabilities(snapshot: dict, cfg) -> dict:
    model_id = snapshot.get("id") or ""
    formats = ["wav", "pcm"]
    if getattr(cfg, "mp3_enabled", False):
        formats.append("mp3")
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


def _voice_details(model_id: str, voices: list[str], snapshot: dict, cfg) -> list[dict]:
    capabilities = _model_capabilities(snapshot, cfg)
    return [
        {
            "id": str(voice),
            "name": str(voice),
            "display_name": _voice_display_name(str(voice), model_id),
            "lang": "zh-CN",
            "locale": "zh-CN",
            "gender": _guess_voice_gender(str(voice), model_id),
            "role_hints": _role_hints_for_gender(_guess_voice_gender(str(voice), model_id)),
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


class ModelSwitchRequest(BaseModel):
    model: str
    unload_previous: bool | None = None


def create_status_router(state: ServiceState, verify_api_key, templates=None) -> APIRouter:
    router = APIRouter()
    cfg = state.cfg

    def _admin_required():
        if not cfg.metrics_enabled:
            raise HTTPException(status_code=404, detail="Metrics disabled")

    async def _verify_status_endpoint_access(request: Request):
        if getattr(cfg, "public_status_endpoints", True):
            return
        await verify_api_key(request)

    def _public_catalog_allowed() -> bool:
        return bool(getattr(cfg, "public_status_endpoints", True)) or not bool(cfg.api_key)

    def _minimal_bootstrap(current_model: dict | None = None) -> dict:
        current_model = current_model or state.model_manager.current_snapshot()
        return {
            "voices": [],
            "models": [],
            "currentModel": "",
            "defaultVoice": cfg.default_voice,
            "defaultSpeed": cfg.default_speed,
            "maxTextLength": cfg.max_text_length,
            "sampleRate": current_model.get("sample_rate") or cfg.sample_rate,
            "authRequired": bool(cfg.api_key),
            "catalogProtected": True,
            "streamEnabled": cfg.stream_enabled,
            "streamBinaryEnabled": cfg.stream_binary_enabled,
            "mp3Enabled": getattr(cfg, "mp3_enabled", False),
            "modelSwitchEnabled": getattr(cfg, "model_switch_enabled", True),
            "adminEnabled": bool(getattr(cfg, "admin_enabled", False)),
            "apiKeyFile": str(getattr(cfg, "api_key_file", "") or ""),
        }

    def _minimal_health(status: str, is_healthy: bool, unhealthy_models: list[str]) -> dict:
        return {
            "status": status,
            "healthy": is_healthy,
            "unhealthy_models": unhealthy_models,
            "name": "AngeVoice",
            "deployment_profile": str(getattr(cfg, "deployment_profile", "source") or "source"),
            "auth_required": bool(cfg.api_key),
            "catalog_protected": not _public_catalog_allowed(),
            "stream_enabled": cfg.stream_enabled,
        }

    def _model_catalog_snapshot(target_model: str) -> dict:
        """返回模型元数据和音色列表，不触发模型实际加载。"""
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

    @router.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        if templates:
            current_model = state.model_manager.current_snapshot()
            voices = current_model.get("voices") or []
            if _public_catalog_allowed():
                bootstrap = {
                    "voices": voices,
                    "models": state.model_manager.list_models(),
                    "currentModel": state.model_manager.current_model_id,
                    "defaultVoice": current_model.get("default_voice") or cfg.default_voice,
                    "defaultSpeed": cfg.default_speed,
                    "maxTextLength": cfg.max_text_length,
                    "sampleRate": current_model.get("sample_rate") or cfg.sample_rate,
                    "authRequired": bool(cfg.api_key),
                    "catalogProtected": False,
                    "streamEnabled": cfg.stream_enabled,
                    "streamBinaryEnabled": cfg.stream_binary_enabled,
                    "mp3Enabled": getattr(cfg, "mp3_enabled", False),
                    "modelSwitchEnabled": getattr(cfg, "model_switch_enabled", True),
                    "adminEnabled": bool(getattr(cfg, "admin_enabled", False)),
                    "apiKeyFile": str(getattr(cfg, "api_key_file", "") or ""),
                }
            else:
                bootstrap = _minimal_bootstrap(current_model)
                voices = []
            return templates.TemplateResponse(
                request,
                "index.html",
                {
                    "voices": voices,
                    "bootstrap": bootstrap,
                },
            )
        return HTMLResponse("<h1>AngeVoice</h1><p>Built on Kokoro v1.1 model.</p>")

    @router.get("/api-docs", response_class=HTMLResponse)
    async def api_docs(request: Request):
        """返回带有可复制 MOSS 克隆示例的 API 文档页。"""
        if templates:
            current_model = state.model_manager.current_snapshot()
            if _public_catalog_allowed():
                bootstrap = {
                    "models": state.model_manager.list_models(),
                    "currentModel": state.model_manager.current_model_id,
                    "authRequired": bool(cfg.api_key),
                    "catalogProtected": False,
                    "defaultVoice": current_model.get("default_voice") or cfg.default_voice,
                    "streamEnabled": cfg.stream_enabled,
                    "streamBinaryEnabled": cfg.stream_binary_enabled,
                    "mp3Enabled": getattr(cfg, "mp3_enabled", False),
                    "mossPromptUploadMaxBytes": getattr(cfg, "moss_prompt_upload_max_bytes", 0),
                    "mossPromptAudioMaxSeconds": getattr(cfg, "moss_prompt_audio_max_seconds", 0),
                    "adminEnabled": bool(getattr(cfg, "admin_enabled", False)),
                    "apiKeyFile": str(getattr(cfg, "api_key_file", "") or ""),
                }
            else:
                bootstrap = _minimal_bootstrap(current_model)
                bootstrap.update({
                    "mossPromptUploadMaxBytes": getattr(cfg, "moss_prompt_upload_max_bytes", 0),
                    "mossPromptAudioMaxSeconds": getattr(cfg, "moss_prompt_audio_max_seconds", 0),
                })
            return templates.TemplateResponse(
                request,
                "api_docs.html",
                {"bootstrap": bootstrap},
            )
        return HTMLResponse(
            "<h1>AngeVoice API Docs</h1>"
            "<p>Install the package with template support to view the full documentation page.</p>"
        )

    @router.get("/health")
    async def health():
        current_model = state.model_manager.current_snapshot()
        voices = current_model.get("voices") or []
        # 检查是否存在已加载但 unhealthy 的模型
        all_models = state.model_manager.list_models()
        unhealthy_models = [
            m["id"] for m in all_models
            if m.get("loaded") and not m.get("healthy", True)
        ]
        is_healthy = not unhealthy_models
        if unhealthy_models:
            status = "degraded"
        elif current_model.get("loaded"):
            status = "ok"
        elif current_model.get("idle_unloaded"):
            status = "idle"
        else:
            status = "loading"
        if not _public_catalog_allowed():
            return _minimal_health(status, is_healthy, unhealthy_models)
        return {
            "status": status,
            "healthy": is_healthy,
            "unhealthy_models": unhealthy_models,
            "name": "AngeVoice",
            "deployment_profile": str(getattr(cfg, "deployment_profile", "source") or "source"),
            "model_base": current_model.get("name") or "unknown",
            "model": current_model,
            "models": state.model_manager.list_models(),
            "current_model": state.model_manager.current_model_id,
            "device": current_model.get("device"),
            "voices": voices,
            "sample_rate": current_model.get("sample_rate") or cfg.sample_rate,
            "max_concurrent_requests": cfg.max_concurrent_requests,
            "cache_enabled": cfg.cache_enabled,
            "cache_items": state.cache_size(),
            "cache_bytes": state.cache_bytes(),
            "batch_enabled": getattr(cfg, "batch_enabled", False),
            "admin_enabled": getattr(cfg, "admin_enabled", False),
            "mp3_enabled": getattr(cfg, "mp3_enabled", False),
            "auth_required": bool(cfg.api_key),
            "stream_enabled": cfg.stream_enabled,
        }

    @router.get("/v1/audio/voices")
    async def list_voices(
        model: str | None = None,
        detail: bool = True,
        _=Depends(_verify_status_endpoint_access),
    ):
        target_model = state.model_manager.normalize_model_id(model)
        snapshot = _model_catalog_snapshot(target_model)
        voices = snapshot.get("voices") or []
        response = {
            "model": target_model,
            "voices": voices,
            "count": len(voices),
            "default_voice": snapshot.get("default_voice") or cfg.default_voice,
            "capabilities": _model_capabilities(snapshot, cfg),
        }
        if detail:
            response["voice_details"] = _voice_details(target_model, voices, snapshot, cfg)
        return response

    @router.get("/v1/tts/capabilities")
    async def tts_capabilities(include_voices: bool = True, _=Depends(_verify_status_endpoint_access)):
        models = []
        for model in state.model_manager.list_models():
            model_id = str(model.get("id") or "")
            snapshot = _model_catalog_snapshot(model_id)
            voices = snapshot.get("voices") or []
            item = _model_capabilities(snapshot, cfg)
            item["voice_count"] = len(voices)
            if include_voices:
                item["voices"] = _voice_details(model_id, voices, snapshot, cfg)
            models.append(item)
        formats = ["wav", "pcm"] + (["mp3"] if getattr(cfg, "mp3_enabled", False) else [])
        return {
            "service": "AngeVoice",
            "version": __version__,
            "current_model": state.model_manager.current_model_id,
            "auth_required": bool(cfg.api_key),
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
            "models": state.model_manager.list_models(),
        }

    @router.get("/v1/models/current")
    async def current_model(_=Depends(_verify_status_endpoint_access)):
        return state.model_manager.current_snapshot()

    @router.get("/v1/engines/parameter-schema")
    async def engine_parameter_schema(_=Depends(_verify_status_endpoint_access)):
        return {"schemas": state.parameter_schema.schema_catalog()}

    @router.post("/v1/models/switch")
    async def switch_model(req: ModelSwitchRequest, _=Depends(verify_api_key)):
        if not cfg.model_switch_enabled:
            raise HTTPException(status_code=404, detail="Model switch API disabled")
        try:
            result = await run_in_threadpool(
                state.model_manager.switch_model,
                req.model,
                unload_previous=req.unload_previous,
                load=True,
            )
            state.cache_clear()
            return result
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.post("/v1/models/{model_id}/load")
    async def load_model(model_id: str, _=Depends(verify_api_key)):
        if not cfg.model_switch_enabled:
            raise HTTPException(status_code=404, detail="Model management API disabled")
        try:
            engine = await run_in_threadpool(state.model_manager.get_engine, model_id, load=True)
            metadata = engine.metadata() if hasattr(engine, "metadata") and callable(engine.metadata) else {}
            if not isinstance(metadata, dict):
                metadata = state.model_manager.current_snapshot()
            return {
                "ok": True,
                "model": metadata,
            }
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.post("/v1/models/{model_id}/unload")
    async def unload_model(model_id: str, _=Depends(verify_api_key)):
        if not cfg.model_switch_enabled:
            raise HTTPException(status_code=404, detail="Model management API disabled")
        removed = await run_in_threadpool(state.model_manager.unload_model, model_id)
        if removed:
            state.cache_clear()
        return {"ok": True, "model": state.model_manager.normalize_model_id(model_id), "unloaded": removed}

    @router.get("/stats")
    async def get_stats(_=Depends(verify_api_key)):
        _admin_required()
        snapshot = state.snapshot_stats()
        uptime = time.time() - snapshot["started_at"]

        # 队列与并发信息：使用 ServiceState 的稳定快照接口。
        requests_snapshot = state.request_snapshot()
        active = [r for r in requests_snapshot if r.get("status") in {"queued", "running", "cancelling"}]
        queued = [r for r in active if r.get("status") == "queued"]

        # 延迟百分位统计
        latency = state.latency_tracker.summary()

        # 模型信息
        all_models = state.model_manager.list_models()
        current_model = state.model_manager.current_snapshot()

        # 显存信息
        vram = _get_vram_usage()

        requests_total = snapshot.get("requests_total", 0)
        requests_ok = snapshot.get("requests_ok", 0)
        requests_error = snapshot.get("requests_error", 0)

        return {
            "uptime_seconds": round(uptime, 3),
            # 保持向后兼容的扁平字段（现有测试和旧客户端仍会读取）
            "requests_total": requests_total,
            "requests_ok": requests_ok,
            "requests_error": requests_error,
            # 结构化请求信息块。
            "requests": {
                "total": requests_total,
                "ok": requests_ok,
                "error": requests_error,
            },
            "active_requests": len(active),
            "queue_length": len(queued),
            "latency": latency,
            "models": {
                "current": current_model,
                "available": all_models,
            },
            "vram": vram,
            "cache_items": state.cache_size(),
            "cache_bytes": state.cache_bytes(),
            "cache_enabled": cfg.cache_enabled,
        }

    @router.get("/v1/diagnostics/resources")
    async def resource_diagnostics(_=Depends(verify_api_key)):
        return state.resource_snapshot()

    @router.post("/v1/diagnostics/resources/release")
    async def release_resources(unload_models: bool = False, include_current: bool = True, _=Depends(verify_api_key)):
        return await run_in_threadpool(
            state.release_resources, clear_cache=True, unload_models=unload_models, include_current=include_current
        )

    @router.post("/v1/admin/cache/clear")
    async def clear_cache_release_compat(unload_models: bool = False, include_current: bool = True, _=Depends(verify_api_key)):
        """Compatibility alias for NAS validation clients that called the R0 cache clear path."""
        result = await run_in_threadpool(
            state.release_resources, clear_cache=True, unload_models=unload_models, include_current=include_current
        )
        result["compatibility_alias"] = "/v1/admin/cache/clear"
        result["canonical_endpoint"] = "/v1/diagnostics/resources/release"
        return result

    @router.get("/requests")
    async def get_requests(_=Depends(verify_api_key)):
        if not cfg.queue_status_enabled:
            raise HTTPException(status_code=404, detail="Queue status disabled")
        return {"requests": state.request_snapshot(limit=100, recent_first=True)}

    @router.post("/v1/audio/requests/{request_id}/cancel")
    async def cancel_request(request_id: str, _=Depends(verify_api_key)):
        known = state.request_cancel(request_id)
        return {"ok": True, "request_id": request_id, "known": known, "status": "cancelling"}

    return router
