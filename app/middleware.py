"""HTTP-level protections: metrics, rate limiting, and body size enforcement."""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from typing import Deque, Dict

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from . import metrics
from .config import settings

logger = logging.getLogger("agenttrafficcop.middleware")


# ---------------------------------------------------------------------------
# Metrics middleware
# ---------------------------------------------------------------------------


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        endpoint = request.url.path
        method = request.method
        started = time.perf_counter()

        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            duration = time.perf_counter() - started
            try:
                metrics.inc_request(endpoint, method, 500)
                metrics.observe_latency(endpoint, duration)
            except Exception:
                pass
            raise

        duration = time.perf_counter() - started
        try:
            metrics.inc_request(endpoint, method, status_code)
            metrics.observe_latency(endpoint, duration)
        except Exception:
            pass

        return response


# ---------------------------------------------------------------------------
# Rate limiting — Redis-backed with in-memory fallback
# ---------------------------------------------------------------------------


class _RateLimiter:
    """Per-key rate limiter.

    If Redis is configured, it uses Redis INCR/EXPIRE for global,
    multi-instance accuracy. If Redis is down or not configured, it falls
    back to a thread-safe in-process sliding window.
    """

    def __init__(self, max_per_window: int, window_seconds: int = 60, max_clients: int = 10000) -> None:
        self._max = max_per_window
        self._window = window_seconds
        self._max_clients = max_clients
        
        # Try to connect to Redis
        self._redis = None
        if settings.redis_url:
            try:
                import redis
                self._redis = redis.Redis.from_url(
                    settings.redis_url, 
                    decode_responses=True,
                    socket_timeout=2.0,
                    socket_connect_timeout=2.0
                )
                self._redis.ping()
                logger.info("rate_limiter_using_redis url=%s", settings.redis_url)
            except Exception as e:
                logger.warning("rate_limiter_redis_failed error=%s falling_back=in_memory", e)
                self._redis = None
                
        # Fallback in-memory store
        self._calls: Dict[str, Deque[float]] = {}

    def check(self, key: str) -> tuple[bool, int]:
        """Record a call for *key*. Returns (allowed, retry_after_seconds)."""
        
        # --- REDIS IMPLEMENTATION ---
        if self._redis:
            now = int(time.time())
            # Fixed window bucket (e.g. 1-minute windows)
            bucket = now // self._window
            redis_key = f"atc:rl:{key}:{bucket}"
            
            try:
                pipe = self._redis.pipeline()
                pipe.incr(redis_key)
                pipe.expire(redis_key, self._window)
                count, _ = pipe.execute()
                
                if count > self._max:
                    # Calculate how many seconds until the next bucket starts
                    retry_after = self._window - (now % self._window)
                    return False, max(1, retry_after)
                return True, 0
            except Exception as e:
                logger.error("redis_rate_limit_failed error=%s falling_back=in_memory", e)
                # Fall through to in-memory if Redis fails mid-request
        
        # --- IN-MEMORY FALLBACK ---
        now_mono = time.monotonic()
        cutoff = now_mono - self._window

        if len(self._calls) > self._max_clients:
            keys_to_remove = list(self._calls.keys())[:int(self._max_clients * 0.1)]
            for k in keys_to_remove:
                del self._calls[k]

        if key not in self._calls:
            self._calls[key] = deque()

        calls = self._calls[key]

        while calls and calls[0] < cutoff:
            calls.popleft()

        if len(calls) >= self._max:
            oldest = calls[0]
            retry_after = max(1, int(self._window - (now_mono - oldest)) + 1)
            return False, retry_after

        calls.append(now_mono)
        return True, 0


_limiters = {
    "free": _RateLimiter(max_per_window=settings.tier_free_rate_limit),
    "pro": _RateLimiter(max_per_window=settings.tier_pro_rate_limit),
    "team": _RateLimiter(max_per_window=settings.tier_team_rate_limit),
}


def _client_key(request: Request) -> str:
    """Identify the caller for rate-limiting purposes.

    FIX (C5): X-Forwarded-For is now only trusted when ATC_TRUST_PROXY=true.
    The old code trusted it unconditionally, which meant:

      * Direct-connection attackers could send `XFF: 1.2.3.4` on every
        request → new "IP" each time → rate limit never fired.
      * Behind a proxy, the client-supplied XFF was *prepended*, so the
        first value was the client's own string — still spoofable.

    When trust_proxy is on, we take the LAST hop (the proxy-added one),
    which is the closest thing to a trustworthy address.
    """
    if settings.trust_proxy:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            # Last entry = added by the nearest trusted proxy.
            return xff.split(",")[-1].strip()
    if request.client is not None:
        return request.client.host
    return "unknown"


async def check_rate_limit(request: Request, key_fingerprint: str) -> None:
    """Enforce the rate limit based on the user's tier."""
    from .usage import get_tier_and_limit, _resolve_usage_key
    from .exceptions import RateLimitError

    tier, _ = get_tier_and_limit(key_fingerprint)
    resolved_key = _resolve_usage_key(key_fingerprint)

    limiter = _limiters.get(tier, _limiters["free"])
    allowed, retry_after = limiter.check(resolved_key)

    if not allowed:
        logger.warning(
            "rate_limit_exceeded tier=%s key=%s path=%s",
            tier, resolved_key, request.url.path,
        )
        raise RateLimitError(
            message=f"Rate limit for {tier} tier exceeded.",
            retry_after=retry_after,
        )


# ---------------------------------------------------------------------------
# Body size enforcement
# ---------------------------------------------------------------------------


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests whose body exceeds the configured limit.

    FIX (H5): the original only checked the Content-Length header. A
    request with `Transfer-Encoding: chunked` (or a lying Content-Length)
    could bypass the limit and stream gigabytes through /v1/route.

    Now we always read the actual body and enforce the cap on real bytes.
    For requests under the cap this buffers up to `max_body_bytes` (1MB
    default) — acceptable overhead, and the only version that's actually
    correct. For true stream-level enforcement, terminate the connection
    at a proxy (nginx client_max_body_size, etc.).
    """

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next):
        # Read once and cache. Starlette's request.body() caches internally,
        # so downstream handlers still see the same bytes.
        try:
            body = await request.body()
        except Exception as e:
            logger.warning("body_read_failed path=%s error=%s", request.url.path, e)
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "error": "REQUEST_READ_FAILED",
                    "message": "Could not read request body.",
                    "session_id": None,
                    "diagnostics": {},
                },
            )

        if len(body) > self.max_bytes:
            logger.warning(
                "body_too_large path=%s actual_bytes=%d max_bytes=%d",
                request.url.path, len(body), self.max_bytes,
            )
            return JSONResponse(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                content={
                    "error": "REQUEST_TOO_LARGE",
                    "message": (
                        f"Request body exceeds the maximum of "
                        f"{self.max_bytes} bytes."
                    ),
                    "session_id": None,
                    "diagnostics": {
                        "max_bytes": self.max_bytes,
                        "actual_bytes": len(body),
                    },
                },
            )

        return await call_next(request)


# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------


def install_middleware(app: FastAPI) -> None:
    """Wire HTTP-level protections into the app."""
    app.add_middleware(
        BodySizeLimitMiddleware,
        max_bytes=settings.max_body_bytes,
    )
    app.add_middleware(MetricsMiddleware)

    logger.info(
        "middleware_installed max_body_bytes=%d rate_limit_per_minute=%d "
        "metrics_enabled=%s trust_proxy=%s",
        settings.max_body_bytes,
        settings.rate_limit_per_minute,
        settings.metrics_enabled,
        settings.trust_proxy,
    )