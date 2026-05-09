"""Token-bucket rate limiting and concurrent-queue middleware for AngeVoice.

Both middlewares are **no-ops** when their respective config values are 0
(disabled), so production deployments pay zero overhead when not configured.

Environment variables (all read via ``TTSConfig``):
    KOKORO_RATE_LIMIT_QPS        – requests per second per client (0 = disabled)
    KOKORO_RATE_LIMIT_BURST      – max burst tokens in the bucket
    KOKORO_MAX_QUEUE_LENGTH      – max concurrent in-flight requests (0 = disabled)
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

    __slots__ = (
        "_qps",
        "_burst",
        "_buckets",
        "_lock",
        "_last_cleanup",
        "_cleanup_interval",
    )

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

    def __init__(self, app, qps: float, burst: int) -> None:  # noqa: ANN001
        super().__init__(app)
        self._registry = _BucketRegistry(qps, burst)

    async def dispatch(self, request: Request, call_next):  # noqa: ANN201
        client_key = _extract_client_key(request)
        bucket = self._registry.get_bucket(client_key)
        if bucket.acquire():
            return await call_next(request)

        retry = bucket.retry_after
        logger.warning("Rate limit exceeded for %s (retry-after=%.1fs)", client_key, retry)
        return JSONResponse(
            status_code=429,
            content={
                "error": "rate_limit_exceeded",
                "message": "Too many requests. Please slow down.",
                "retry_after": round(retry, 2),
            },
            headers={"Retry-After": str(max(1, int(retry) + 1))},
        )


class GlobalQueueMiddleware(BaseHTTPMiddleware):
    """Limits total concurrent in-flight requests via an ``asyncio.Semaphore``."""

    def __init__(self, app, max_concurrent: int) -> None:  # noqa: ANN001
        super().__init__(app)
        self._semaphore = asyncio.Semaphore(max(1, int(max_concurrent)))
        self._max = max(1, int(max_concurrent))

    async def dispatch(self, request: Request, call_next):  # noqa: ANN201
        try:
            await asyncio.wait_for(self._semaphore.acquire(), timeout=0)
        except asyncio.TimeoutError:
            logger.warning("Global queue full (%d/%d)", self._max, self._max)
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
            self._semaphore.release()


def _extract_client_key(request: Request) -> str:
    """Return a string key identifying the client for rate-limit bucketing."""
    api_key: Optional[str] = request.headers.get("x-api-key")
    if not api_key:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            api_key = auth[7:].strip()
    if api_key:
        return f"key:{api_key}"

    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return f"ip:{forwarded.split(',')[0].strip()}"
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return f"ip:{real_ip}"
    if request.client:
        return f"ip:{request.client.host}"
    return "ip:unknown"
