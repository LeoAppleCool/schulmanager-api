from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from schulmanager_api.config import Settings, get_settings
from schulmanager_api.dependencies import get_cache_store
from schulmanager_api.services import metrics_store

router = APIRouter(tags=["metrics"])


@router.get("/metrics", include_in_schema=False)
async def prometheus_metrics(
    settings: Settings = Depends(get_settings),
    cache: Any = Depends(get_cache_store),
) -> Response:
    """Prometheus metrics endpoint. Optionally requires admin JWT when SM_METRICS_REQUIRE_AUTH=true."""
    # Update live cache gauges
    try:
        stats = cache.stats()
        metrics_store.cache_keys.set(stats["key_count"])
        metrics_store.cache_hit_rate.set(stats["hit_rate"])
    except Exception:
        pass
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
