from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any


@dataclass(slots=True)
class CacheEntry:
    value: Any
    expires_at: datetime


class InMemoryTTLCache:
    """Thread-safe TTL cache backed by an in-process dict."""

    backend_name = "memory"

    def __init__(self) -> None:
        self._lock = Lock()
        self._cache: dict[str, CacheEntry] = {}
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Any | None:
        now = datetime.now(timezone.utc)
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self._misses += 1
                return None
            if entry.expires_at <= now:
                self._cache.pop(key, None)
                self._misses += 1
                return None
            self._hits += 1
            return entry.value

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=max(ttl_seconds, 1))
        with self._lock:
            self._cache[key] = CacheEntry(value=value, expires_at=expires_at)

    def delete_prefix(self, prefix: str) -> None:
        with self._lock:
            keys = [key for key in self._cache if key.startswith(prefix)]
            for key in keys:
                self._cache.pop(key, None)

    def flush(self) -> None:
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0

    def stats(self) -> dict[str, Any]:
        with self._lock:
            now = datetime.now(timezone.utc)
            active_keys = sum(1 for e in self._cache.values() if e.expires_at > now)
            total = self._hits + self._misses
            hit_rate = self._hits / total if total > 0 else 0.0
            return {
                "backend": self.backend_name,
                "key_count": active_keys,
                "hit_count": self._hits,
                "miss_count": self._misses,
                "hit_rate": round(hit_rate, 4),
            }
