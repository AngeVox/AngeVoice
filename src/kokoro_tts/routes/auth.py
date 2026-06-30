"""Studio browser API-key session routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import JSONResponse

from ..config_api_key import effective_api_key
from ..security import (
    API_SESSION_COOKIE,
    API_SESSION_MAX_AGE_SECONDS,
    _constant_time_equal,
    _extract_bearer_token,
    create_api_session_cookie,
)


def create_auth_router(cfg) -> APIRouter:
    router = APIRouter()

    @router.post("/v1/auth/session")
    async def create_browser_session(request: Request):
        expected_key = effective_api_key(cfg)
        token = _extract_bearer_token(request.headers.get("Authorization", ""))
        if not expected_key or not _constant_time_equal(token, expected_key):
            raise HTTPException(status_code=401, detail="Invalid or missing API key")

        response = JSONResponse({"ok": True, "expires_in": API_SESSION_MAX_AGE_SECONDS})
        response.set_cookie(
            API_SESSION_COOKIE,
            create_api_session_cookie(expected_key),
            max_age=API_SESSION_MAX_AGE_SECONDS,
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="lax",
            path="/",
        )
        return response

    @router.delete("/v1/auth/session")
    async def clear_browser_session():
        response = JSONResponse({"ok": True})
        response.delete_cookie(API_SESSION_COOKIE, path="/")
        return response

    return router
