from __future__ import annotations

from functools import lru_cache

from schulmanager_api.config import get_settings
from schulmanager_api.providers.base import SchulmanagerProvider
from schulmanager_api.providers.mock import MockSchulmanagerProvider
from schulmanager_api.providers.selenium import SeleniumSchulmanagerProvider


@lru_cache(maxsize=1)
def get_provider_instance() -> SchulmanagerProvider:
    settings = get_settings()

    backend = settings.backend.strip().lower()
    if backend == "mock":
        return MockSchulmanagerProvider()
    if backend == "selenium":
        return SeleniumSchulmanagerProvider()

    raise ValueError(
        f"Unbekanntes Backend '{settings.backend}'. Erlaubt: mock, selenium"
    )
