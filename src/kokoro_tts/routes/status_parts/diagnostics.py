"""Read-only diagnostic routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from . import StatusRouteContext


def attach_diagnostic_routes(router: APIRouter, ctx: StatusRouteContext) -> None:
    state = ctx.state

    @router.get("/v1/diagnostics/resources")
    async def resource_diagnostics(_=Depends(ctx.verify_api_key)):
        return state.resource_snapshot()

