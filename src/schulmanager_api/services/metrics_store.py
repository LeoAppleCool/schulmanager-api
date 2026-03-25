from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# HTTP layer
http_requests_total = Counter(
    "schulmanager_http_requests_total",
    "Total HTTP requests handled",
    ["method", "path", "status_code"],
)

# Webhook delivery
webhook_deliveries_total = Counter(
    "schulmanager_webhook_deliveries_total",
    "Webhook delivery attempts",
    ["status"],  # "success" | "failure"
)

# Cache operations (populated from cache.stats())
cache_keys = Gauge("schulmanager_cache_keys", "Current live cache key count")
cache_hit_rate = Gauge("schulmanager_cache_hit_rate", "Cache hit rate (0-1)")

# API sync
syncs_total = Counter(
    "schulmanager_syncs_total",
    "POST /sync/refresh calls",
    ["status"],  # "success" | "error"
)
