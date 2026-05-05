"""Status, health, voice listing and Web UI routes."""

import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from ..service_state import ServiceState


def create_status_router(state: ServiceState, verify_api_key, templates=None) -> APIRouter:
    router = APIRouter()
    cfg = state.cfg
    eng = state.eng

    @router.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        if templates:
            voices = cfg.get_voices()
            return templates.TemplateResponse(request, "index.html", {"voices": voices})
        return HTMLResponse("<h1>AngeVoice</h1><p>Built on Kokoro v1.1 model.</p>")

    @router.get("/health")
    async def health():
        return {
            "status": "ok" if eng.is_loaded else "loading",
            "name": "AngeVoice",
            "model_base": "Kokoro v1.1",
            "device": eng._device,
            "voices": cfg.get_voices(),
            "sample_rate": cfg.sample_rate,
            "max_concurrent_requests": cfg.max_concurrent_requests,
            "cache_enabled": cfg.cache_enabled,
            "cache_items": len(state.tts_cache),
            "batch_enabled": getattr(cfg, "batch_enabled", False),
            "admin_enabled": getattr(cfg, "admin_enabled", False),
            "mp3_enabled": getattr(cfg, "mp3_enabled", False),
        }

    @router.get("/v1/audio/voices")
    async def list_voices():
        return {"voices": cfg.get_voices()}

    @router.get("/stats")
    async def get_stats(_=Depends(verify_api_key)):
        if not cfg.metrics_enabled:
            raise HTTPException(status_code=404, detail="Metrics disabled")
        snapshot = state.snapshot_stats()
        uptime = time.time() - snapshot["started_at"]
        return {
            **snapshot,
            "uptime_seconds": round(uptime, 3),
            "cache_items": len(state.tts_cache),
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
