import logging

from fastapi import FastAPI

from schulmanager_api.config import get_settings
from schulmanager_api.dependencies import get_rate_limiter_store
from schulmanager_api.routers.auth import router as auth_router
from schulmanager_api.routers.cache import router as cache_router
from schulmanager_api.routers.health import router as health_router
from schulmanager_api.routers.metrics import router as metrics_router
from schulmanager_api.routers.students import router as students_router
from schulmanager_api.routers.sync import router as sync_router
from schulmanager_api.routers.webhooks import router as webhooks_router
from schulmanager_api.services.logging_config import setup_logging
from schulmanager_api.services.rate_limiter import RateLimitMiddleware

settings = get_settings()

setup_logging(settings.log_format, settings.log_level)


def _startup_config_warnings() -> None:
    log = logging.getLogger("schulmanager_api.startup")
    is_prod = settings.environment.strip().lower() in {"production", "prod"}
    if not settings.admin_emails:
        log.warning(
            "SM_ADMIN_EMAILS_CSV is empty — no account gets the admin role, so /cache/* "
            "(and /metrics when SM_METRICS_REQUIRE_AUTH=true) will reject everyone."
        )
    if settings.jwt_secret == "change-me-in-production":
        (log.error if is_prod else log.warning)("SM_JWT_SECRET is still the default — set a strong secret.")
    if settings.webhooks_enabled and settings.webhook_hmac_secret == "change-webhook-secret":
        (log.error if is_prod else log.warning)("SM_WEBHOOK_HMAC_SECRET is still the default — set a strong secret.")


_startup_config_warnings()

app = FastAPI(
    title=settings.app_name,
    description="Modulare API fuer Schulmanager-Daten",
    version="0.5.0",
)

app.add_middleware(
    RateLimitMiddleware,
    settings=settings,
    limiter=get_rate_limiter_store(),
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(students_router)
app.include_router(webhooks_router)
app.include_router(sync_router)
app.include_router(cache_router)
app.include_router(metrics_router)


@app.middleware("http")
async def force_json_charset(request, call_next):  # type: ignore[no-untyped-def]
    response = await call_next(request)
    content_type = response.headers.get("content-type", "")
    if content_type.startswith("application/json") and "charset=" not in content_type.lower():
        response.headers["content-type"] = "application/json; charset=utf-8"
    return response


from schulmanager_api.services import metrics_store as _ms


@app.middleware("http")
async def count_requests(request, call_next):
    response = await call_next(request)
    path = request.url.path
    # Collapse parameterised paths to avoid cardinality explosion
    if path.startswith("/students/"):
        path = "/students/{...}"
    _ms.http_requests_total.labels(
        method=request.method, path=path, status_code=str(response.status_code)
    ).inc()
    return response


def run() -> None:
    import uvicorn

    uvicorn.run("schulmanager_api.main:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    run()
