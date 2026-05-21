"""AngeVoice 管理后台路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from starlette.concurrency import run_in_threadpool

from ..admin_auth import (
    candidate_encodings as _candidate_encodings,
    make_verify_admin,
    parse_basic_header as _parse_basic_header,
    safe_compare as _safe_compare,
)
from ..service_state import ServiceState
from ..admin_config_schema import export_env_patch, schema_payload
from .admin_models import (
    AdminApiKeyAction,
    AdminConfigPatch,
    AdminModelAction,
    AdminProfileAction,
    AdminSingleModelAction,
    AdminSwitchModelAction,
)
from .admin_runtime import (
    admin_config_payload,
    apply_config_patch,
    apply_config_profile,
    clear_runtime_config_file,
    config_snapshot,
    rotate_api_key,
    security_snapshot,
)


def create_admin_router(state: ServiceState) -> APIRouter:
    router = APIRouter()
    cfg = state.cfg
    verify_admin = make_verify_admin(cfg)

    @router.get("/admin", response_class=HTMLResponse)
    async def admin_panel(request: Request, _=Depends(verify_admin)):
        templates = getattr(state, "templates", None)
        if templates is not None:
            return templates.TemplateResponse(request, "admin.html", {})
        return HTMLResponse("<h1>AngeVoice Admin</h1><p>Template support is unavailable.</p>")

    def _active_requests_snapshot() -> list[dict]:
        with state.request_lock:
            return list(state.active_requests.values())[-50:]

    @router.get("/admin/api/status")
    async def admin_status(_=Depends(verify_admin)):
        return {
            "current_model": state.model_manager.current_model_id,
            "models": state.model_manager.list_models(),
            "cache_items": state.cache_size(),
            "cache_bytes": state.cache_bytes(),
            "active_requests": _active_requests_snapshot(),
            "stats": state.snapshot_stats(),
            "security": security_snapshot(cfg),
            "config": config_snapshot(cfg),
        }

    @router.get("/admin/api/security")
    async def admin_security(reveal: bool = False, _=Depends(verify_admin)):
        return security_snapshot(cfg, reveal=reveal)

    @router.post("/admin/api/security/key")
    async def admin_rotate_key(req: AdminApiKeyAction, _=Depends(verify_admin)):
        if req.rotate:
            rotate_api_key(cfg)
        return security_snapshot(cfg, reveal=True)

    @router.get("/admin/api/config")
    async def admin_get_config(_=Depends(verify_admin)):
        return admin_config_payload(cfg)

    @router.get("/admin/api/config/schema")
    async def admin_get_config_schema(_=Depends(verify_admin)):
        return schema_payload()

    @router.get("/admin/api/config/env")
    async def admin_get_config_env(_=Depends(verify_admin)):
        values = admin_config_payload(cfg)["values"]
        return {"env": export_env_patch(values), "config": config_snapshot(cfg)}

    @router.delete("/admin/api/config/runtime")
    async def admin_clear_runtime_config(_=Depends(verify_admin)):
        removed = clear_runtime_config_file(cfg)
        return {"ok": True, "removed": removed, "config": config_snapshot(cfg)}

    @router.patch("/admin/api/config")
    async def admin_patch_config(req: AdminConfigPatch, _=Depends(verify_admin)):
        changed, restart_required, rebuild_moss = apply_config_patch(cfg, req)
        rebuilt: list[str] = []
        if rebuild_moss:
            for model_id in ("moss-nano-cpu", "moss-nano-cuda"):
                if state.model_manager.drop_model(model_id, force=False, raise_if_busy=False):
                    rebuilt.append(model_id)
            if rebuilt:
                state.cache_clear()
        return {
            "ok": True,
            "changed": changed,
            "restart_required": restart_required,
            "model_rebuild_required": rebuild_moss,
            "rebuilt_models": rebuilt,
            "config": config_snapshot(cfg),
            "env_patch": export_env_patch(admin_config_payload(cfg)["values"], only=changed),
        }

    @router.post("/admin/api/config/profile")
    async def admin_apply_profile(req: AdminProfileAction, _=Depends(verify_admin)):
        changed, restart_required, rebuild_moss = apply_config_profile(cfg, req.profile)
        rebuilt: list[str] = []
        if rebuild_moss:
            for model_id in ("moss-nano-cpu", "moss-nano-cuda"):
                if state.model_manager.drop_model(model_id, force=False, raise_if_busy=False):
                    rebuilt.append(model_id)
            if rebuilt:
                state.cache_clear()
        return {
            "ok": True,
            "profile": req.profile,
            "changed": changed,
            "restart_required": restart_required,
            "model_rebuild_required": rebuild_moss,
            "rebuilt_models": rebuilt,
            "config": config_snapshot(cfg),
            "env_patch": export_env_patch(admin_config_payload(cfg)["values"], only=changed),
        }

    @router.delete("/admin/api/cache")
    async def admin_clear_cache(_=Depends(verify_admin)):
        cleared = state.cache_clear()
        return {"ok": True, "cleared": cleared}

    @router.post("/admin/api/models/switch")
    async def admin_switch_model(req: AdminSwitchModelAction, _=Depends(verify_admin)):
        result = await run_in_threadpool(
            state.model_manager.switch_model,
            req.model,
            unload_previous=req.unload_previous,
            load=req.load,
        )
        state.cache_clear()
        return result

    @router.post("/admin/api/models/unload")
    async def admin_unload_models(req: AdminModelAction, _=Depends(verify_admin)):
        unloaded = await run_in_threadpool(
            state.model_manager.unload_inactive,
            force=req.force,
            include_current=req.include_current,
        )
        if unloaded:
            state.cache_clear()
        return {"ok": True, "unloaded": unloaded, "force": req.force}

    @router.post("/admin/api/models/{model_id}/load")
    async def admin_load_model(model_id: str, _=Depends(verify_admin)):
        engine = await run_in_threadpool(state.model_manager.get_engine, model_id, load=True)
        metadata = engine.metadata() if hasattr(engine, "metadata") and callable(engine.metadata) else {}
        return {"ok": True, "model": metadata}

    @router.post("/admin/api/models/{model_id}/unload")
    async def admin_unload_model(model_id: str, req: AdminSingleModelAction | None = None, _=Depends(verify_admin)):
        force = bool(req.force) if req is not None else False
        removed = await run_in_threadpool(state.model_manager.unload_model, model_id, force=force, raise_if_busy=False)
        if removed:
            state.cache_clear()
        return {"ok": True, "model": state.model_manager.normalize_model_id(model_id), "unloaded": removed, "force": force}

    return router
