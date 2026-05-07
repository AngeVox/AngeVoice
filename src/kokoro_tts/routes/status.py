"""Status, health, voice listing and Web UI routes."""

import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from ..service_state import ServiceState


class ModelSwitchRequest(BaseModel):
    model: str
    unload_previous: bool | None = None


def create_status_router(state: ServiceState, verify_api_key, templates=None) -> APIRouter:
    router = APIRouter()
    cfg = state.cfg

    @router.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        if templates:
            current_model = state.model_manager.current_snapshot()
            voices = current_model.get("voices") or []
            bootstrap = {
                "voices": voices,
                "models": state.model_manager.list_models(),
                "currentModel": state.model_manager.current_model_id,
                "defaultVoice": current_model.get("default_voice") or cfg.default_voice,
                "defaultSpeed": cfg.default_speed,
                "maxTextLength": cfg.max_text_length,
                "sampleRate": current_model.get("sample_rate") or cfg.sample_rate,
                "authRequired": bool(cfg.api_key),
                "streamEnabled": cfg.stream_enabled,
                "streamBinaryEnabled": cfg.stream_binary_enabled,
                "mp3Enabled": getattr(cfg, "mp3_enabled", False),
                "modelSwitchEnabled": getattr(cfg, "model_switch_enabled", True),
            }
            return templates.TemplateResponse(
                request,
                "index.html",
                {
                    "voices": voices,
                    "bootstrap": bootstrap,
                },
            )
        return HTMLResponse("<h1>AngeVoice</h1><p>Built on Kokoro v1.1 model.</p>")

    @router.get("/health")
    async def health():
        current_model = state.model_manager.current_snapshot()
        voices = current_model.get("voices") or []
        return {
            "status": "ok" if current_model.get("loaded") else "loading",
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
    async def list_voices(model: str | None = None):
        target_model = state.model_manager.normalize_model_id(model)
        snapshot = state.model_manager.current_snapshot()
        if target_model != state.model_manager.current_model_id:
            engine = state.model_manager.get_engine(target_model, load=False)
            voices = engine.get_voices() if hasattr(engine, "get_voices") else []
        else:
            voices = snapshot.get("voices") or []
        return {"model": target_model, "voices": voices}

    @router.get("/v1/models")
    async def list_models():
        return {
            "current_model": state.model_manager.current_model_id,
            "models": state.model_manager.list_models(),
        }

    @router.get("/v1/models/current")
    async def current_model():
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
        if not cfg.metrics_enabled:
            raise HTTPException(status_code=404, detail="Metrics disabled")
        snapshot = state.snapshot_stats()
        uptime = time.time() - snapshot["started_at"]
        return {
            **snapshot,
            "uptime_seconds": round(uptime, 3),
            "cache_items": state.cache_size(),
            "active_requests": len([r for r in state.active_requests.values() if r.get("status") in {"queued", "running", "cancelling"}]),
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
