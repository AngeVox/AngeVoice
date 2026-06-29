"""Model and resource control routes with side effects."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from . import StatusRouteContext


class ModelSwitchRequest(BaseModel):
    model: str
    unload_previous: bool | None = None


def attach_control_routes(router: APIRouter, ctx: StatusRouteContext) -> None:
    state = ctx.state
    cfg = ctx.cfg

    @router.post("/v1/models/switch")
    async def switch_model(req: ModelSwitchRequest, _=Depends(ctx.verify_api_key)):
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
    async def load_model(model_id: str, _=Depends(ctx.verify_api_key)):
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
    async def unload_model(model_id: str, _=Depends(ctx.verify_api_key)):
        if not cfg.model_switch_enabled:
            raise HTTPException(status_code=404, detail="Model management API disabled")
        removed = await run_in_threadpool(state.model_manager.unload_model, model_id)
        if removed:
            state.cache_clear()
            restart = state.handle_model_unload_completed([state.model_manager.normalize_model_id(model_id)], reason="manual")
        else:
            restart = state.idle_restart_snapshot()
        return {"ok": True, "model": state.model_manager.normalize_model_id(model_id), "unloaded": removed, "restart": restart}

    @router.post("/v1/diagnostics/resources/release")
    async def release_resources(unload_models: bool = False, include_current: bool = True, _=Depends(ctx.verify_admin)):
        return await run_in_threadpool(
            state.release_resources, clear_cache=True, unload_models=unload_models, include_current=include_current
        )

    @router.post("/v1/admin/cache/clear")
    async def clear_cache_release_compat(unload_models: bool = False, include_current: bool = True, _=Depends(ctx.verify_admin)):
        """旧版缓存清理别名；现在与管理后台一样要求 Admin Auth。"""
        result = await run_in_threadpool(
            state.release_resources, clear_cache=True, unload_models=unload_models, include_current=include_current
        )
        result["compatibility_alias"] = "/v1/admin/cache/clear"
        result["canonical_endpoint"] = "/v1/diagnostics/resources/release"
        return result

    @router.post("/v1/audio/requests/{request_id}/cancel")
    async def cancel_request(request_id: str, _=Depends(ctx.verify_api_key)):
        known = state.request_cancel(request_id)
        return {
            "ok": True,
            "request_id": request_id,
            "known": known,
            "status": "cancelling",
        }

