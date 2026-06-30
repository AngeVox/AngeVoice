"""Token-bucket rate limiting and concurrent-queue middleware for AngeVoice.

Both middlewares are **no-ops** when their respective config values are 0
(disabled), so production deployments pay zero overhead when not configured.

Environment variables (all read via ``TTSConfig``):
    KOKORO_RATE_LIMIT_QPS        – requests per second per client (0 = disabled)
    KOKORO_RATE_LIMIT_BURST      – max burst tokens in the bucket
    KOKORO_MAX_QUEUE_LENGTH      – max concurrent in-flight requests (0 = disabled)
    KOKORO_TRUST_PROXY_HEADERS   – trust X-Forwarded-For/X-Real-IP only behind a reverse proxy
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


class TokenBucket:
    """Classic token-bucket rate limiter, one instance per client key."""

    __slots__ = ("_qps", "_burst", "_tokens", "_last_refill", "_lock")

    def __init__(self, qps: float, burst: int) -> None:
        self._qps = max(0.0, float(qps))
        self._burst = max(1, int(burst))
        self._tokens = float(self._burst)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> bool:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self._burst, self._tokens + elapsed * self._qps)
            self._last_refill = now
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False

    @property
    def retry_after(self) -> float:
        with self._lock:
            if self._tokens >= 1.0:
                return 0.0
            return (1.0 - self._tokens) / self._qps if self._qps > 0 else 1.0

    @property
    def idle(self) -> bool:
        with self._lock:
            return self._tokens >= float(self._burst)


class _BucketRegistry:
    """Manages per-key ``TokenBucket`` instances with automatic cleanup."""

    __slots__ = ("_qps", "_burst", "_buckets", "_lock", "_last_cleanup", "_cleanup_interval")

    def __init__(self, qps: float, burst: int) -> None:
        self._qps = max(0.0, float(qps))
        self._burst = max(1, int(burst))
        self._buckets: dict[str, TokenBucket] = {}
        self._lock = threading.Lock()
        self._last_cleanup = time.monotonic()
        self._cleanup_interval = 60.0

    def get_bucket(self, key: str) -> TokenBucket:
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = TokenBucket(self._qps, self._burst)
                self._buckets[key] = bucket
            self._maybe_cleanup()
            return bucket

    def _maybe_cleanup(self) -> None:
        now = time.monotonic()
        if now - self._last_cleanup < self._cleanup_interval:
            return
        self._last_cleanup = now
        stale = [key for key, bucket in self._buckets.items() if bucket.idle]
        for key in stale:
            del self._buckets[key]


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Token-bucket rate limiter applied per client IP or API key."""

    def __init__(self, app, qps: float, burst: int, trust_proxy_headers: bool = False) -> None:  # noqa: ANN001
        super().__init__(app)
        self._registry = _BucketRegistry(qps, burst)
        self._trust_proxy_headers = bool(trust_proxy_headers)

    async def dispatch(self, request: Request, call_next):  # noqa: ANN201
        client_key = _extract_client_key(request, trust_proxy_headers=self._trust_proxy_headers)
        bucket = self._registry.get_bucket(client_key)
        if bucket.acquire():
            return await call_next(request)

        retry = bucket.retry_after
        logger.warning("Rate limit exceeded for %s (retry-after=%.1fs)", _safe_client_log_label(client_key), retry)
        return JSONResponse(
            status_code=429,
            content={
                "error": "rate_limit_exceeded",
                "message": "Too many requests. Please slow down.",
                "retry_after": round(retry, 2),
            },
            headers={"Retry-After": str(max(1, int(retry) + 1))},
        )


class _NonBlockingConcurrencyGate:
    """Small public-state gate used instead of peeking at asyncio.Semaphore._value."""

    def __init__(self, max_concurrent: int) -> None:
        self._max = max(1, int(max_concurrent))
        self._in_flight = 0
        self._lock = asyncio.Lock()

    @property
    def max_concurrent(self) -> int:
        return self._max

    @property
    def in_flight(self) -> int:
        return self._in_flight

    async def acquire_nowait(self) -> bool:
        async with self._lock:
            if self._in_flight >= self._max:
                return False
            self._in_flight += 1
            return True

    async def release(self) -> None:
        async with self._lock:
            self._in_flight = max(0, self._in_flight - 1)


class GlobalQueueMiddleware(BaseHTTPMiddleware):
    """Limits total concurrent in-flight requests without private asyncio APIs."""

    def __init__(self, app, max_concurrent: int) -> None:  # noqa: ANN001
        super().__init__(app)
        self._gate = _NonBlockingConcurrencyGate(max_concurrent)

    async def dispatch(self, request: Request, call_next):  # noqa: ANN201
        if not await self._gate.acquire_nowait():
            logger.warning(
                "Global queue full (%d/%d)",
                self._gate.in_flight,
                self._gate.max_concurrent,
            )
            return JSONResponse(
                status_code=429,
                content={
                    "error": "queue_full",
                    "message": "Server is at capacity. Please retry shortly.",
                },
                headers={"Retry-After": "1"},
            )
        try:
            return await call_next(request)
        finally:
            await self._gate.release()


def _extract_client_key(request: Request, *, trust_proxy_headers: bool = False) -> str:
    """Return a string key identifying the client for rate-limit bucketing.

    Proxy headers are ignored by default because public clients can spoof
    ``X-Forwarded-For`` when the service is exposed without a trusted reverse
    proxy. Set ``KOKORO_TRUST_PROXY_HEADERS=true`` only behind Nginx/Caddy/Traefik.
    """
    api_key: Optional[str] = request.headers.get("x-api-key")
    if not api_key:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            api_key = auth[7:].strip()
    if api_key:
        return "key:present"

    if trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return f"ip:{forwarded.split(',')[0].strip()}"
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return f"ip:{real_ip}"
    if request.client:
        return f"ip:{request.client.host}"
    return "ip:unknown"


def _safe_client_log_label(client_key: str) -> str:
    """Return a non-secret client label for logs."""
    return "key:present" if client_key.startswith("key:") else client_key
