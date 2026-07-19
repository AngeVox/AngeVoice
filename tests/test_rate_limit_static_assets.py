from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from kokoro_tts.rate_limit import RateLimitMiddleware


def _client() -> TestClient:
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, qps=0.01, burst=1)

    @app.api_route("/static/example.js", methods=["GET", "HEAD", "POST"])
    @app.api_route("/static", methods=["GET", "HEAD"])
    @app.api_route("/static-evil/example.js", methods=["GET"])
    @app.api_route("/api/static/example.js", methods=["GET"])
    @app.get("/api/ping")
    def endpoint():
        return {"ok": True}

    return TestClient(app)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/static/example.js"),
        ("head", "/static/example.js"),
        ("get", "/static/example.js?v=hash"),
        ("get", "/static"),
    ],
)
def test_static_asset_reads_bypass_the_api_token_bucket(method: str, path: str) -> None:
    client = _client()

    assert getattr(client, method)(path).status_code == 200
    assert client.get("/api/ping").status_code == 200
    assert client.get("/api/ping").status_code == 429


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/static/example.js"),
        ("get", "/static-evil/example.js"),
        ("get", "/api/static/example.js"),
    ],
)
def test_non_read_or_non_static_paths_still_consume_the_api_token_bucket(method: str, path: str) -> None:
    client = _client()

    assert getattr(client, method)(path).status_code == 200
    assert client.get("/api/ping").status_code == 429


def test_api_rate_limit_response_shape_and_retry_after_are_unchanged() -> None:
    client = _client()

    assert client.get("/api/ping").status_code == 200
    limited = client.get("/api/ping")
    assert limited.status_code == 429
    assert limited.json()["error"] == "rate_limit_exceeded"
    assert limited.json()["message"] == "Too many requests. Please slow down."
    assert isinstance(limited.json()["retry_after"], float)
    retry_after = limited.json()["retry_after"]
    retry_after_header = int(limited.headers["Retry-After"])
    # The JSON value is rounded to two decimals, while Retry-After is derived
    # from the unrounded internal value; do not reconstruct the header here.
    assert retry_after_header >= 1
    assert retry_after_header - 1 <= retry_after <= retry_after_header
