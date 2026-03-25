from __future__ import annotations

from functools import lru_cache
from typing import Any, Callable

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from schulmanager_api.config import Settings, get_settings
from schulmanager_api.models.schemas import Role
from schulmanager_api.providers.base import SchulmanagerProvider
from schulmanager_api.providers.factory import get_provider_instance
from schulmanager_api.services.auth_store import InMemoryAuthStore
from schulmanager_api.services.event_service import EventMonitor, EventService
from schulmanager_api.services.rate_limiter import InMemoryRateLimiter
from schulmanager_api.services.security import AuthPrincipal, JWTAuthService
from schulmanager_api.services.webhooks import InMemoryWebhookRegistry, WebhookDispatcher

security = HTTPBearer(auto_error=False)


@lru_cache(maxsize=1)
def get_auth_store() -> InMemoryAuthStore:
    return InMemoryAuthStore()


@lru_cache(maxsize=1)
def get_cache_store() -> Any:
    settings = get_settings()
    backend = settings.cache_backend.lower()
    if backend == "sqlite":
        from schulmanager_api.services.sqlite_cache import SQLiteTTLCache
        return SQLiteTTLCache(settings.cache_db_path)
    # default: memory
    from schulmanager_api.services.cache import InMemoryTTLCache
    return InMemoryTTLCache()


@lru_cache(maxsize=1)
def get_rate_limiter_store() -> InMemoryRateLimiter:
    return InMemoryRateLimiter()


@lru_cache(maxsize=1)
def get_webhook_registry() -> InMemoryWebhookRegistry:
    return InMemoryWebhookRegistry()


@lru_cache(maxsize=1)
def get_event_monitor() -> EventMonitor:
    return EventMonitor()


def get_provider() -> SchulmanagerProvider:
    return get_provider_instance()


def get_auth_service(
    settings: Settings = Depends(get_settings),
    store: InMemoryAuthStore = Depends(get_auth_store),
) -> JWTAuthService:
    return JWTAuthService(settings=settings, store=store)


def get_webhook_dispatcher(
    settings: Settings = Depends(get_settings),
    registry: InMemoryWebhookRegistry = Depends(get_webhook_registry),
) -> WebhookDispatcher:
    return WebhookDispatcher(settings=settings, registry=registry)


def get_event_service(
    monitor: EventMonitor = Depends(get_event_monitor),
    dispatcher: WebhookDispatcher = Depends(get_webhook_dispatcher),
) -> EventService:
    return EventService(monitor=monitor, dispatcher=dispatcher)


def get_current_principal(
    auth: HTTPAuthorizationCredentials | None = Depends(security),
    auth_service: JWTAuthService = Depends(get_auth_service),
) -> AuthPrincipal:
    if auth is None or not auth.credentials:
        raise HTTPException(status_code=401, detail="Authorization Bearer Token fehlt")

    try:
        return auth_service.decode_access_principal(auth.credentials)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def require_roles(*allowed: Role) -> Callable[[AuthPrincipal], AuthPrincipal]:
    def _check(principal: AuthPrincipal = Depends(get_current_principal)) -> AuthPrincipal:
        if principal.role in allowed:
            return principal
        raise HTTPException(status_code=403, detail="Keine Berechtigung fuer diese Operation")

    return _check
