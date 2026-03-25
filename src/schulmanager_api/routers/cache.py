from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from schulmanager_api.dependencies import get_cache_store, require_roles
from schulmanager_api.models.schemas import CacheStats, Role

router = APIRouter(prefix="/cache", tags=["cache"])


@router.get("/stats", response_model=CacheStats)
async def cache_stats(
    _principal: Any = Depends(require_roles(Role.ADMIN)),
    cache: Any = Depends(get_cache_store),
) -> CacheStats:
    """Return cache hit rate, key count, and backend type (admin only)."""
    raw = cache.stats()
    return CacheStats(
        backend=raw["backend"],
        key_count=raw["key_count"],
        hit_count=raw["hit_count"],
        miss_count=raw["miss_count"],
        hit_rate=raw["hit_rate"],
    )


@router.delete("", status_code=204, response_class=Response)
async def flush_cache(
    _principal: Any = Depends(require_roles(Role.ADMIN)),
    cache: Any = Depends(get_cache_store),
) -> Response:
    """Flush all cached data (admin only)."""
    cache.flush()
    return Response(status_code=204)
