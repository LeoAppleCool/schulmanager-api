from fastapi import APIRouter, Depends, HTTPException, Response

from schulmanager_api.config import Settings, get_settings
from schulmanager_api.dependencies import (
    get_webhook_dispatcher,
    get_webhook_registry,
    require_roles,
)
from schulmanager_api.models.schemas import (
    Role,
    WebhookCreateRequest,
    WebhookEventType,
    WebhookSubscriptionInfo,
)
from schulmanager_api.services.security import AuthPrincipal
from schulmanager_api.services.webhooks import InMemoryWebhookRegistry, WebhookDispatcher, to_info

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("", response_model=WebhookSubscriptionInfo)
async def register_webhook(
    payload: WebhookCreateRequest,
    principal: AuthPrincipal = Depends(require_roles(Role.ADMIN, Role.PARENT)),
    registry: InMemoryWebhookRegistry = Depends(get_webhook_registry),
    settings: Settings = Depends(get_settings),
) -> WebhookSubscriptionInfo:
    if not settings.webhooks_enabled:
        raise HTTPException(status_code=400, detail="Webhooks sind deaktiviert")

    subscription = registry.create(
        url=str(payload.url),
        event_types=payload.event_types,
        secret=payload.secret,
    )
    return to_info(subscription)


@router.get("", response_model=list[WebhookSubscriptionInfo])
async def list_webhooks(
    principal: AuthPrincipal = Depends(require_roles(Role.ADMIN, Role.PARENT)),
    registry: InMemoryWebhookRegistry = Depends(get_webhook_registry),
) -> list[WebhookSubscriptionInfo]:
    return [to_info(item) for item in registry.list()]


@router.delete("/{subscription_id}", status_code=204)
async def delete_webhook(
    subscription_id: str,
    principal: AuthPrincipal = Depends(require_roles(Role.ADMIN, Role.PARENT)),
    registry: InMemoryWebhookRegistry = Depends(get_webhook_registry),
) -> Response:
    deleted = registry.delete(subscription_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Webhook nicht gefunden")
    return Response(status_code=204)


@router.post("/test", response_model=dict[str, int])
async def send_test_webhook(
    principal: AuthPrincipal = Depends(require_roles(Role.ADMIN, Role.PARENT)),
    dispatcher: WebhookDispatcher = Depends(get_webhook_dispatcher),
) -> dict[str, int]:
    delivered = await dispatcher.dispatch(
        WebhookEventType.TEST,
        {
            "account_id": principal.account_id,
            "message": "test event",
        },
    )
    return {"delivered": delivered}
