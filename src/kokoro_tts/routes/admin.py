"""AngeVoice 管理后台路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response
from starlette.concurrency import run_in_threadpool

from ..admin_credentials import AdminCredentialStore
from ..admin_auth import (
    candidate_encodings as _candidate_encodings,
    make_verify_admin,
    parse_basic_header as _parse_basic_header,
    safe_compare as _safe_compare,
)
from ..service_state import ServiceState
from ..model_assets import ModelAssetService
from ..diagnostics import build_diagnostics_bundle
from ..update_checker import UpdateChecker
from ..admin_config_schema import export_env_patch, schema_payload
from .admin_models import (
    AdminApiKeyAction,
    AdminAssetRepairAction,
    AdminCredentialUpdate,
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
    model_assets = ModelAssetService(cfg)
    update_checker = UpdateChecker(cfg)

    @router.get("/admin", response_class=HTMLResponse)
    async def admin_panel(request: Request, _=Depends(verify_admin)):
        templates = getattr(state, "templates", None)
        if templates is not None:
            return templates.TemplateResponse(request, "admin.html", {})
        return HTMLResponse("<h1>AngeVoice Admin</h1><p>Template support is unavailable.</p>")

    def _active_requests_snapshot() -> list[dict]:
        with state.request_lock:
            values = list(state.active_requests.values())
        return sorted(values, key=lambda item: float(item.get("updated_at", 0) or 0), reverse=True)[:50]

    @router.get("/admin/api/status")
    async def admin_status(_=Depends(verify_admin)):
        return {
            "current_model": state.model_manager.current_model_id,
            "models": state.model_manager.list_models(),
            "cache_items": state.cache_size(),
            "cache_bytes": state.cache_bytes(),
            "active_requests": _active_requests_snapshot(),
            "stats": state.snapshot_stats(),
            "resources": state.resource_snapshot(),
            "security": security_snapshot(cfg),
            "config": config_snapshot(cfg),
            "update": update_checker.snapshot(),
        }

    @router.get("/admin/api/security")
    async def admin_security(reveal: bool = False, _=Depends(verify_admin)):
        return security_snapshot(cfg, reveal=reveal)

    @router.get("/admin/api/update")
    async def admin_update_snapshot(_=Depends(verify_admin)):
        return update_checker.snapshot()

    @router.post("/admin/api/update/check")
    async def admin_check_update(force: bool = False, _=Depends(verify_admin)):
        return await run_in_threadpool(update_checker.check, force=force)

    @router.post("/admin/api/security/key")
    async def admin_rotate_key(req: AdminApiKeyAction, _=Depends(verify_admin)):
        if req.rotate:
            rotate_api_key(cfg)
        return security_snapshot(cfg, reveal=True)

    @router.put("/admin/api/security/credentials")
    async def admin_update_credentials(req: AdminCredentialUpdate, _=Depends(verify_admin)):
        try:
            status = AdminCredentialStore(cfg).set_credentials(req.username, req.password)
        except ValueError as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "ok": True,
            "admin_credentials": status,
            "auth_source": "persisted_hash",
            "message": "管理员凭据已安全保存，请使用新账号密码重新登录。",
        }

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
            for model_id in ("moss",):
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
            for model_id in ("moss",):
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
        result = await run_in_threadpool(state.release_resources, clear_cache=True, unload_models=False)
        result["cleared"] = result["cleared_cache_items"]
        return result

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

    @router.get("/admin/api/assets")
    async def admin_asset_status(full_verify_zipvoice: bool = False, _=Depends(verify_admin)):
        return await run_in_threadpool(model_assets.status, full_verify_zipvoice=full_verify_zipvoice)

    @router.get("/admin/api/diagnostics/bundle")
    async def admin_diagnostics_bundle(_=Depends(verify_admin)):
        payload = await run_in_threadpool(build_diagnostics_bundle, state)
        return Response(
            content=payload,
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="angevoice-diagnostics.zip"'},
        )

    @router.post("/admin/api/assets/{model_id}/repair")
    async def admin_repair_assets(model_id: str, req: AdminAssetRepairAction | None = None, _=Depends(verify_admin)):
        force = bool(req.force_unload) if req else False
        target_id = state.model_manager.normalize_model_id(model_id)
        await run_in_threadpool(state.model_manager.unload_model, target_id, force=force, raise_if_busy=True)
        state.cache_clear()
        try:
            repaired = await run_in_threadpool(model_assets.repair, model_id)
        except ValueError as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        repaired["resource_status"] = state.resource_snapshot()
        return repaired

    return router
