"""状态、健康检查、音色列表和 Web UI 路由。"""

from fastapi import APIRouter

from ..admin_auth import make_verify_admin
from ..service_state import ServiceState
from .status_parts import StatusRouteContext
from .status_parts.control import attach_control_routes
from .status_parts.diagnostics import attach_diagnostic_routes
from .status_parts.health import attach_health_routes, bootstrap_base
from .status_parts.models import attach_model_routes
from .status_parts.runtime import attach_runtime_routes, get_vram_usage

_bootstrap_base = bootstrap_base
_get_vram_usage = get_vram_usage


def create_status_router(state: ServiceState, verify_api_key, templates=None) -> APIRouter:
    router = APIRouter()
    ctx = StatusRouteContext(
        state=state,
        cfg=state.cfg,
        verify_api_key=verify_api_key,
        verify_admin=make_verify_admin(state.cfg),
        templates=templates,
    )

    attach_health_routes(router, ctx)
    attach_model_routes(router, ctx)
    attach_control_routes(router, ctx)
    attach_runtime_routes(router, ctx)
    attach_diagnostic_routes(router, ctx)
    return router
