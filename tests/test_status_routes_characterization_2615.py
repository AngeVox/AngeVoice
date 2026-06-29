from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from kokoro_tts.config import TTSConfig
from kokoro_tts.server import create_app


def _fake_engine() -> MagicMock:
    engine = MagicMock()
    engine.is_loaded = True
    engine.is_healthy = True
    engine.default_voice = "zm_010"
    engine.get_voices.return_value = ["zm_010"]
    engine.metadata.return_value = {"id": "kokoro", "loaded": True}
    engine.config = MagicMock(sample_rate=24000, max_text_length=10000)
    return engine


def _route_signature(app) -> dict[str, set[tuple[str, str]]]:
    signatures: dict[str, set[tuple[str, str]]] = {}
    pending = list(app.routes)
    while pending:
        route = pending.pop(0)
        inner = getattr(route, "original_router", None)
        if inner is not None:
            pending.extend(getattr(inner, "routes", []))
            continue
        path = getattr(route, "path", None)
        if not isinstance(path, str):
            continue
        methods = getattr(route, "methods", None) or {""}
        for method in methods:
            signatures.setdefault(path, set()).add((str(method), str(getattr(route, "name", ""))))
    return signatures


def test_2615_status_route_surface_is_stable_and_starlette_router_safe(tmp_path):
    app = create_app(
        config=TTSConfig(
            admin_enabled=True,
            api_key="api-token",
            public_status_endpoints=False,
            admin_credentials_file=tmp_path / "admin-credentials.json",
        ),
        engine=_fake_engine(),
    )
    routes = _route_signature(app)

    expected = {
        "/": {("GET", "index")},
        "/api-docs": {("GET", "api_docs")},
        "/health": {("GET", "health")},
        "/v1/audio/voices": {("GET", "list_voices")},
        "/v1/tts/capabilities": {("GET", "tts_capabilities")},
        "/v1/models": {("GET", "list_models")},
        "/v1/models/current": {("GET", "current_model")},
        "/v1/engines/parameter-schema": {("GET", "engine_parameter_schema")},
        "/v1/models/switch": {("POST", "switch_model")},
        "/v1/models/{model_id}/load": {("POST", "load_model")},
        "/v1/models/{model_id}/unload": {("POST", "unload_model")},
        "/stats": {("GET", "get_stats")},
        "/v1/diagnostics/resources": {("GET", "resource_diagnostics")},
        "/v1/diagnostics/resources/release": {("POST", "release_resources")},
        "/v1/admin/cache/clear": {("POST", "clear_cache_release_compat")},
        "/requests": {("GET", "get_requests")},
        "/v1/audio/requests/{request_id}/cancel": {("POST", "cancel_request")},
    }
    for path, signature in expected.items():
        assert routes[path] == signature


def test_2615_status_auth_boundary_distinguishes_public_read_from_control(tmp_path):
    app = create_app(
        config=TTSConfig(
            admin_enabled=True,
            api_key="api-token",
            public_status_endpoints=False,
            admin_credentials_file=tmp_path / "admin-credentials.json",
        ),
        engine=_fake_engine(),
    )
    client = TestClient(app)

    assert client.get("/health").status_code == 200
    assert client.get("/v1/models").status_code == 401
    assert client.get("/v1/audio/voices").status_code == 401
    assert client.post("/v1/models/switch", json={"model": "kokoro"}).status_code == 401
    assert client.post("/v1/diagnostics/resources/release").status_code == 401

    api_headers = {"Authorization": "Bearer api-token"}
    assert client.get("/v1/models", headers=api_headers).status_code == 200
    assert client.post("/v1/models/switch", headers=api_headers, json={"model": "kokoro"}).status_code == 200
    assert client.post("/v1/diagnostics/resources/release", headers=api_headers).status_code == 401


def test_2615_status_parts_do_not_depend_on_status_facade():
    import kokoro_tts.routes.status_parts.control as control
    import kokoro_tts.routes.status_parts.diagnostics as diagnostics
    import kokoro_tts.routes.status_parts.health as health
    import kokoro_tts.routes.status_parts.models as models
    import kokoro_tts.routes.status_parts.runtime as runtime

    for module in (control, diagnostics, health, models, runtime):
        assert "status" not in module.__dict__
