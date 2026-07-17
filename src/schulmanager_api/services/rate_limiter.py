from __future__ import annotations

import hashlib
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from schulmanager_api.config import Settings


@dataclass(slots=True)
class RateLimitState:
    timestamps: deque[datetime]


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._lock = Lock()
        self._state: dict[str, RateLimitState] = {}

    def check(self, key: str, now: datetime, limit: int, window_seconds: int) -> tuple[bool, int]:
        window_start = now - timedelta(seconds=window_seconds)

        with self._lock:
            state = self._state.setdefault(key, RateLimitState(timestamps=deque()))

            while state.timestamps and state.timestamps[0] < window_start:
                state.timestamps.popleft()

            if len(state.timestamps) >= limit:
                oldest = state.timestamps[0]
                retry_after = int((oldest + timedelta(seconds=window_seconds) - now).total_seconds())
                return False, max(retry_after, 1)

            state.timestamps.append(now)
            return True, 0


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: Settings, limiter: InMemoryRateLimiter) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self._settings = settings
        self._limiter = limiter

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        if not self._settings.rate_limit_enabled:
            return await call_next(request)

        path = request.url.path
        if path in {"/health", "/openapi.json", "/docs", "/redoc"}:
            return await call_next(request)

        now = datetime.now(timezone.utc)
        client_ip = self._client_ip(request)
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer ") and len(auth) > 7:
            # Hash the *whole* token so distinct users get distinct buckets. The old code used a
            # fixed slice of the JWT header, which is identical across tokens -> one bucket per IP.
            token_hint = hashlib.sha256(auth[7:].strip().encode("utf-8")).hexdigest()[:16]
        else:
            token_hint = "anon"
        key = f"{client_ip}:{token_hint}"

        allowed, retry_after = self._limiter.check(
            key=key,
            now=now,
            limit=max(self._settings.rate_limit_requests, 1),
            window_seconds=max(self._settings.rate_limit_window_seconds, 1),
        )

        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Rate limit erreicht",
                    "retry_after": retry_after,
                },
                headers={"Retry-After": str(retry_after)},
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self._settings.rate_limit_requests)
        response.headers["X-RateLimit-Window"] = str(self._settings.rate_limit_window_seconds)
        return response

    @staticmethod
    def _client_ip(request: Request) -> str:
        # Behind a reverse proxy the peer is the proxy; prefer the first X-Forwarded-For hop.
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            first = forwarded.split(",")[0].strip()
            if first:
                return first
        return request.client.host if request.client else "unknown"
