"""Pytest configuration: ensure all tests run against the mock provider and in-memory cache."""
from __future__ import annotations

import os

# These must be set before any schulmanager_api module is imported,
# because get_settings() is lru_cached and reads env vars at first call.
# Setting them here (in conftest.py, which pytest loads first) overrides
# whatever is in the local .env file.
os.environ["SM_BACKEND"] = "mock"
os.environ["SM_CACHE_BACKEND"] = "memory"
os.environ["SM_ADMIN_EMAILS_CSV"] = "demo@example.com"
