from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends

from schulmanager_api.config import Settings, get_settings
from schulmanager_api.dependencies import get_cache_store

router = APIRouter(tags=["health"])

_START_TIME = int(time.time())


@router.get("/health")
async def health(
    settings: Settings = Depends(get_settings),
    cache: Any = Depends(get_cache_store),
) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    overall = "ok"

    # Cache check
    try:
        stats = cache.stats()
        checks["cache"] = {"status": "ok", "backend": stats["backend"]}
    except Exception as exc:
        checks["cache"] = {"status": "error", "detail": str(exc)[:200]}
        overall = "degraded"

    # Provider check (lightweight — just report configured backend)
    checks["provider"] = {"status": "ok", "backend": settings.backend}

    return {
        "status": overall,
        "service": settings.app_name,
        "uptime_seconds": int(time.time()) - _START_TIME,
        "checks": checks,
    }
