"""状态、健康检查、音色列表和 Web UI 路由。"""

import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

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
            "auth_required": bool(cfg.api_key),
            "catalog_protected": not _public_catalog_allowed(),
            "stream_enabled": cfg.stream_enabled,
        }

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
            "batch_enabled": getattr(cfg, "batch_enabled", False),
            "admin_enabled": getattr(cfg, "admin_enabled", False),
            "mp3_enabled": getattr(cfg, "mp3_enabled", False),
            "auth_required": bool(cfg.api_key),
            "stream_enabled": cfg.stream_enabled,
        }

    @router.get("/v1/audio/voices")
    async def list_voices(model: str | None = None, _=Depends(_verify_status_endpoint_access)):
        target_model = state.model_manager.normalize_model_id(model)
        snapshot = state.model_manager.current_snapshot()
        if target_model != state.model_manager.current_model_id:
            engine = state.model_manager.get_engine(target_model, load=False)
            voices = engine.get_voices() if hasattr(engine, "get_voices") else []
        else:
            voices = snapshot.get("voices") or []
        return {"model": target_model, "voices": voices}

    @router.get("/v1/models")
    async def list_models(_=Depends(_verify_status_endpoint_access)):
        return {
            "current_model": state.model_manager.current_model_id,
            "models": state.model_manager.list_models(),
        }

    @router.get("/v1/models/current")
    async def current_model(_=Depends(_verify_status_endpoint_access)):
        return state.model_manager.current_snapshot()

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

        # 队列与并发信息
        active = [r for r in state.active_requests.values() if r.get("status") in {"queued", "running", "cancelling"}]
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
            "cache_enabled": cfg.cache_enabled,
        }

    @router.get("/requests")
    async def get_requests(_=Depends(verify_api_key)):
        if not cfg.queue_status_enabled:
            raise HTTPException(status_code=404, detail="Queue status disabled")
        return {"requests": list(state.active_requests.values())[-100:]}

    @router.post("/v1/audio/requests/{request_id}/cancel")
    async def cancel_request(request_id: str, _=Depends(verify_api_key)):
        known = state.request_cancel(request_id)
        return {"ok": True, "request_id": request_id, "known": known, "status": "cancelling"}

    return router
