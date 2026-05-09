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


# ---------------------------------------------------------------------------
# Token bucket (thread-safe, for per-client QPS limiting)
# ---------------------------------------------------------------------------

class TokenBucket:
    """Classic token-bucket rate limiter, one instance per client key.

    Tokens refill continuously at *qps* tokens/second up to *burst*.
    ``acquire()`` returns ``True`` when a token is consumed, ``False`` when
    the bucket is empty (request should be rejected).
    """

    __slots__ = ("_qps", "_burst", "_tokens", "_last_refill", "_lock")

    def __init__(self, qps: float, burst: int) -> None:
        self._qps = qps
        self._burst = burst
        self._tokens = float(burst)  # start full
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
        """Seconds until the next token becomes available (approximate)."""
        with self._lock:
            if self._tokens >= 1.0:
                return 0.0
            return (1.0 - self._tokens) / self._qps if self._qps > 0 else 1.0


# ---------------------------------------------------------------------------
# Per-client bucket registry
# ---------------------------------------------------------------------------

class _BucketRegistry:
    """Manages per-key ``TokenBucket`` instances with automatic cleanup."""

    __slots__ = ("_qps", "_burst", "_buckets", "_lock")

    def __init__(self, qps: float, burst: int) -> None:
        self._qps = qps
        self._burst = burst
        self._buckets: dict[str, TokenBucket] = {}
        self._lock = threading.Lock()
        self._last_cleanup = time.monotonic()
        self._cleanup_interval = 60.0  # seconds

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
        # Evict buckets that are at full capacity (idle clients)
        stale = [
            k
            for k, b in self._buckets.items()
            if b._tokens >= b._burst  # noqa: SLF001 – intentional access
        ]
        for k in stale:
            del self._buckets[k]


# ---------------------------------------------------------------------------
# Rate-limit middleware  (per-IP / per-API-key QPS)
# ---------------------------------------------------------------------------

class RateLimitMiddleware(BaseHTTPMiddleware):
    """Token-bucket rate limiter applied per client IP or API key.

    Extracts the client identity from (in order of priority):
      1. ``X-API-Key`` / ``Authorization: Bearer <key>`` header
      2. ``X-Forwarded-For`` / ``X-Real-IP`` header
      3. ``request.client.host``

    Returns **429 Too Many Requests** with a ``Retry-After`` header when the
    client's bucket is empty.
    """

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


# ---------------------------------------------------------------------------
# Global queue-length middleware (max concurrent in-flight requests)
# ---------------------------------------------------------------------------

class GlobalQueueMiddleware(BaseHTTPMiddleware):
    """Limits total concurrent in-flight requests via an ``asyncio.Semaphore``.

    Returns **429 Too Many Requests** when the semaphore is fully saturated.
    """

    def __init__(self, app, max_concurrent: int) -> None:  # noqa: ANN001
        super().__init__(app)
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._max = max_concurrent

    async def dispatch(self, request: Request, call_next):  # noqa: ANN201
        if self._semaphore.locked():
            logger.warning("Global queue full (%d/%d)", self._max, self._max)
            return JSONResponse(
                status_code=429,
                content={
                    "error": "queue_full",
                    "message": "Server is at capacity. Please retry shortly.",
                },
                headers={"Retry-After": "1"},
            )
        async with self._semaphore:
            return await call_next(request)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_client_key(request: Request) -> str:
    """Return a string key identifying the client for rate-limit bucketing."""
    # Prefer explicit API key if present
    api_key: Optional[str] = request.headers.get("x-api-key")
    if not api_key:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            api_key = auth[7:].strip()
    if api_key:
        return f"key:{api_key}"

    # Fall back to IP
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return f"ip:{forwarded.split(',')[0].strip()}"
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return f"ip:{real_ip}"
    if request.client:
        return f"ip:{request.client.host}"
    return "ip:unknown"
