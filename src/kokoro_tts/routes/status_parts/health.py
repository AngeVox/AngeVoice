"""Health and HTML entrypoint routes."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from starlette.concurrency import run_in_threadpool

from ...audio_formats import ffmpeg_effective_enabled
from ...config_api_key import effective_api_key
from ..admin_runtime import security_snapshot
from . import StatusRouteContext


def auth_required(cfg) -> bool:
    """Return whether status/catalog endpoints need credentials."""
    return bool(effective_api_key(cfg))


def public_catalog_allowed_for_config(cfg) -> bool:
    return bool(getattr(cfg, "public_status_endpoints", True)) or not auth_required(cfg)


def bootstrap_base(cfg, current_model: dict | None = None) -> dict:
    current_model = current_model or {}
    security = security_snapshot(cfg)
    return {
        "defaultVoice": current_model.get("default_voice") or cfg.default_voice,
        "defaultSpeed": cfg.default_speed,
        "maxTextLength": cfg.max_text_length,
        "sampleRate": current_model.get("sample_rate") or cfg.sample_rate,
        "authRequired": auth_required(cfg),
        "streamEnabled": cfg.stream_enabled,
        "streamBinaryEnabled": cfg.stream_binary_enabled,
        "mp3Enabled": ffmpeg_effective_enabled(cfg),
        "ffmpegEnabled": ffmpeg_effective_enabled(cfg),
        "modelSwitchEnabled": getattr(cfg, "model_switch_enabled", True),
        "adminEnabled": bool(getattr(cfg, "admin_enabled", False)),
        "apiKeyFile": str(getattr(cfg, "api_key_file", "") or ""),
        "adminDefaultCredentialsActive": bool(security.get("admin_default_credentials_active")),
        "adminSecurityWarning": str(security.get("admin_security_warning") or ""),
    }


def minimal_bootstrap_payload(cfg, state, current_model: dict | None = None) -> dict:
    current_model = current_model or state.model_manager.current_snapshot()
    payload = {
        "voices": [],
        "models": [],
        "currentModel": "",
        "catalogProtected": True,
    }
    payload.update(bootstrap_base(cfg, current_model))
    return payload


def catalog_bootstrap_payload(cfg, state, current_model: dict | None = None) -> dict:
    current_model = current_model or state.model_manager.current_snapshot()
    payload = {
        "voices": current_model.get("voices") or [],
        "models": state.model_manager.list_models(),
        "currentModel": state.model_manager.current_model_id,
        "catalogProtected": False,
    }
    payload.update(bootstrap_base(cfg, current_model))
    return payload


def minimal_health_payload(
    cfg,
    status: str,
    is_healthy: bool,
    unhealthy_models: list[str],
    restart: dict | None = None,
) -> dict:
    return {
        "status": status,
        "healthy": is_healthy,
        "unhealthy_models": unhealthy_models,
        "restart": restart or {},
        "name": "AngeVoice",
        "deployment_profile": str(getattr(cfg, "deployment_profile", "source") or "source"),
        "auth_required": auth_required(cfg),
        "catalog_protected": not public_catalog_allowed_for_config(cfg),
        "stream_enabled": cfg.stream_enabled,
        "enabled_models": list(getattr(cfg, "enabled_models", []) or []),
    }


def health_status(current_model: dict, unhealthy_models: list[str]) -> str:
    if unhealthy_models:
        return "degraded"
    if current_model.get("loaded"):
        return "ok"
    # 未预加载但可被唤醒的模型是可服务状态，不应被健康检查误判为加载中。
    if current_model.get("idle_unloaded") or current_model.get("wakeable", True):
        return "idle"
    return "loading"


def attach_health_routes(router: APIRouter, ctx: StatusRouteContext) -> None:
    state = ctx.state
    cfg = ctx.cfg
    templates = ctx.templates

    def _public_catalog_allowed() -> bool:
        return public_catalog_allowed_for_config(cfg)

    def _minimal_bootstrap(current_model: dict | None = None) -> dict:
        return minimal_bootstrap_payload(cfg, state, current_model)

    def _minimal_health(status: str, is_healthy: bool, unhealthy_models: list[str], restart: dict | None = None) -> dict:
        return minimal_health_payload(cfg, status, is_healthy, unhealthy_models, restart)

    @router.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        if templates:
            current_model = state.model_manager.current_snapshot()
            if _public_catalog_allowed():
                bootstrap = catalog_bootstrap_payload(cfg, state, current_model)
                voices = bootstrap["voices"]
            else:
                bootstrap = _minimal_bootstrap(current_model)
                voices = []
            # --- Cookie session discovery: tell frontend if a valid session cookie exists ---
            expected_key = effective_api_key(cfg)
            if expected_key:
                from ...security import API_SESSION_COOKIE, verify_api_session_cookie
                cookies = getattr(request, "cookies", {}) or {}
                if verify_api_session_cookie(cookies.get(API_SESSION_COOKIE, ""), expected_key):
                    bootstrap["hasCookieSession"] = True
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
            bootstrap = (
                catalog_bootstrap_payload(cfg, state, current_model)
                if _public_catalog_allowed()
                else _minimal_bootstrap(current_model)
            )
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
        current_model = await run_in_threadpool(
            state.model_manager.current_snapshot,
            include_runtime_metadata=False,
        )
        voices = current_model.get("voices") or []
        all_models = await run_in_threadpool(
            state.model_manager.list_models,
            include_runtime_metadata=False,
        )
        unhealthy_models = [
            m["id"] for m in all_models
            if m.get("loaded") and not m.get("healthy", True)
        ]
        is_healthy = not unhealthy_models
        restart = state.idle_restart_snapshot()
        status = "restarting" if restart.get("scheduled") else health_status(current_model, unhealthy_models)
        if not _public_catalog_allowed():
            return _minimal_health(status, is_healthy, unhealthy_models, restart)
        return {
            "status": status,
            "healthy": is_healthy,
            "unhealthy_models": unhealthy_models,
            "restart": restart,
            "name": "AngeVoice",
            "deployment_profile": str(getattr(cfg, "deployment_profile", "source") or "source"),
            "model_base": current_model.get("name") or "unknown",
            "model": current_model,
            "models": all_models,
            "enabled_models": list(getattr(cfg, "enabled_models", []) or []),
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
            "mp3_enabled": ffmpeg_effective_enabled(cfg),
            "ffmpeg_enabled": ffmpeg_effective_enabled(cfg),
            "auth_required": auth_required(cfg),
            "stream_enabled": cfg.stream_enabled,
        }

