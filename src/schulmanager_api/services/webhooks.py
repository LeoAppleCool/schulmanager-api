from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
from secrets import token_urlsafe
from threading import Lock
from typing import Any

import httpx

from schulmanager_api.config import Settings
from schulmanager_api.models.schemas import WebhookEventType, WebhookSubscriptionInfo
from schulmanager_api.services import metrics_store


@dataclass(slots=True)
class WebhookSubscription:
    id: str
    url: str
    event_types: list[WebhookEventType]
    secret: str | None
    active: bool
    created_at: datetime
    last_delivery_at: datetime | None = None
    last_error: str | None = None


class InMemoryWebhookRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self._items: dict[str, WebhookSubscription] = {}

    def create(self, url: str, event_types: list[WebhookEventType], secret: str | None) -> WebhookSubscription:
        now = datetime.now(timezone.utc)
        subscription = WebhookSubscription(
            id=token_urlsafe(12),
            url=url,
            event_types=event_types,
            secret=secret,
            active=True,
            created_at=now,
        )
        with self._lock:
            self._items[subscription.id] = subscription
        return subscription

    def list(self) -> list[WebhookSubscription]:
        with self._lock:
            return list(self._items.values())

    def delete(self, subscription_id: str) -> bool:
        with self._lock:
            return self._items.pop(subscription_id, None) is not None

    def matching(self, event_type: WebhookEventType) -> list[WebhookSubscription]:
        with self._lock:
            return [
                item
                for item in self._items.values()
                if item.active and event_type in item.event_types
            ]

    def set_delivery(self, subscription_id: str, success: bool, error: str | None) -> None:
        with self._lock:
            item = self._items.get(subscription_id)
            if item is None:
                return
            item.last_delivery_at = datetime.now(timezone.utc)
            item.last_error = None if success else error


class WebhookDispatcher:
    def __init__(self, settings: Settings, registry: InMemoryWebhookRegistry) -> None:
        self._settings = settings
        self._registry = registry

    async def _deliver_with_retry(
        self,
        client: httpx.AsyncClient,
        subscription: WebhookSubscription,
        encoded: bytes,
        headers: dict[str, str],
    ) -> bool:
        delays = [0, 5, 30]
        last_error: str | None = None
        for attempt, delay in enumerate(delays):
            if delay > 0:
                await asyncio.sleep(delay)
            try:
                response = await client.post(subscription.url, content=encoded, headers=headers)
                if 200 <= response.status_code < 300:
                    self._registry.set_delivery(subscription.id, success=True, error=None)
                    metrics_store.webhook_deliveries_total.labels(status="success").inc()
                    return True
                last_error = f"HTTP {response.status_code}"
            except Exception as exc:
                last_error = str(exc)
        self._registry.set_delivery(subscription.id, success=False, error=last_error)
        metrics_store.webhook_deliveries_total.labels(status="failure").inc()
        return False

    async def dispatch(self, event_type: WebhookEventType, payload: dict[str, Any]) -> int:
        if not self._settings.webhooks_enabled:
            return 0

        subscriptions = self._registry.matching(event_type)
        if not subscriptions:
            return 0

        body = {
            "event_type": event_type.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }
        encoded = json.dumps(body, separators=(",", ":"), ensure_ascii=True).encode("utf-8")

        delivered = 0
        timeout = max(self._settings.webhook_timeout_seconds, 1)
        async with httpx.AsyncClient(timeout=timeout) as client:
            for subscription in subscriptions:
                signature = self._signature(encoded, subscription.secret)
                headers = {
                    "Content-Type": "application/json",
                    "X-Schulmanager-Signature": signature,
                    "X-Schulmanager-Event": event_type.value,
                }
                if await self._deliver_with_retry(client, subscription, encoded, headers):
                    delivered += 1
        return delivered

    def _signature(self, payload: bytes, subscription_secret: str | None) -> str:
        key_material = f"{self._settings.webhook_hmac_secret}:{subscription_secret or ''}"
        digest = hmac.new(
            key_material.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()
        return f"sha256={digest}"


def to_info(subscription: WebhookSubscription) -> WebhookSubscriptionInfo:
    return WebhookSubscriptionInfo(
        id=subscription.id,
        url=subscription.url,
        event_types=subscription.event_types,
        active=subscription.active,
        created_at=subscription.created_at,
        last_delivery_at=subscription.last_delivery_at,
        last_error=subscription.last_error,
    )
