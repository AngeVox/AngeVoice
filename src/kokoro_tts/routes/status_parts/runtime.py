"""Runtime statistics and request queue status routes."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException
from starlette.concurrency import run_in_threadpool

from . import StatusRouteContext


def get_vram_usage() -> dict:
    """返回 GPU 显存信息；不可用时返回状态说明。"""
    try:
        import torch  # noqa: F811
        if torch.cuda.is_available():
            device = torch.cuda.current_device()
            props = torch.cuda.get_device_properties(device)
            total = int(getattr(props, "total_memory", getattr(props, "total_mem", 0)) or 0)
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


def attach_runtime_routes(router: APIRouter, ctx: StatusRouteContext) -> None:
    state = ctx.state
    cfg = ctx.cfg

    def _admin_required():
        if not cfg.metrics_enabled:
            raise HTTPException(status_code=404, detail="Metrics disabled")

    @router.get("/stats")
    async def get_stats(_=Depends(ctx.verify_api_key)):
        _admin_required()
        snapshot = state.snapshot_stats()
        uptime = time.time() - snapshot["started_at"]

        requests_snapshot = state.request_snapshot()
        active = [r for r in requests_snapshot if r.get("status") in {"queued", "running", "cancelling"}]
        queued = [r for r in active if r.get("status") == "queued"]

        latency = state.latency_tracker.summary()
        all_models = await run_in_threadpool(
            state.model_manager.list_models,
            include_runtime_metadata=False,
        )
        current_model = await run_in_threadpool(
            state.model_manager.current_snapshot,
            include_runtime_metadata=False,
        )
        vram = await run_in_threadpool(get_vram_usage)

        requests_total = snapshot.get("requests_total", 0)
        requests_ok = snapshot.get("requests_ok", 0)
        requests_error = snapshot.get("requests_error", 0)

        return {
            "uptime_seconds": round(uptime, 3),
            "requests_total": requests_total,
            "requests_ok": requests_ok,
            "requests_error": requests_error,
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
            "restart": state.idle_restart_snapshot(),
        }

    @router.get("/requests")
    async def get_requests(_=Depends(ctx.verify_api_key)):
        if not cfg.queue_status_enabled:
            raise HTTPException(status_code=404, detail="Queue status disabled")
        return {"requests": state.request_snapshot(limit=100, recent_first=True)}

