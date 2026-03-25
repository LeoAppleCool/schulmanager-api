from __future__ import annotations

import json
import pickle
import sqlite3
import time
from pathlib import Path
from threading import Lock
from typing import Any


class SQLiteTTLCache:
    """Thread-safe TTL cache backed by SQLite (synchronous, survives restarts)."""

    backend_name = "sqlite"

    def __init__(self, db_path: str) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._hits = 0
        self._misses = 0
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cache_entries (
                    key TEXT NOT NULL PRIMARY KEY,
                    value BLOB NOT NULL,
                    expires_at INTEGER NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cache_expires ON cache_entries(expires_at)")
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def get(self, key: str) -> Any | None:
        now_ts = int(time.time())
        with self._lock:
            try:
                with self._connect() as conn:
                    cursor = conn.execute(
                        "SELECT value FROM cache_entries WHERE key = ? AND expires_at > ?",
                        (key, now_ts),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        self._misses += 1
                        return None
                    self._hits += 1
                    return pickle.loads(row[0])  # noqa: S301
            except Exception:
                self._misses += 1
                return None

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        expires_at = int(time.time()) + max(ttl_seconds, 1)
        blob = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
        with self._lock:
            try:
                with self._connect() as conn:
                    conn.execute(
                        """
                        INSERT INTO cache_entries (key, value, expires_at)
                        VALUES (?, ?, ?)
                        ON CONFLICT(key) DO UPDATE SET value = excluded.value, expires_at = excluded.expires_at
                        """,
                        (key, blob, expires_at),
                    )
                    conn.commit()
            except Exception:
                pass

    def delete_prefix(self, prefix: str) -> None:
        with self._lock:
            try:
                with self._connect() as conn:
                    conn.execute("DELETE FROM cache_entries WHERE key LIKE ?", (prefix + "%",))
                    conn.commit()
            except Exception:
                pass

    def flush(self) -> None:
        with self._lock:
            try:
                with self._connect() as conn:
                    conn.execute("DELETE FROM cache_entries")
                    conn.commit()
            except Exception:
                pass
            self._hits = 0
            self._misses = 0

    def _evict_expired(self) -> None:
        now_ts = int(time.time())
        try:
            with self._connect() as conn:
                conn.execute("DELETE FROM cache_entries WHERE expires_at <= ?", (now_ts,))
                conn.commit()
        except Exception:
            pass

    def stats(self) -> dict[str, Any]:
        self._evict_expired()
        now_ts = int(time.time())
        with self._lock:
            try:
                with self._connect() as conn:
                    cursor = conn.execute(
                        "SELECT COUNT(*) FROM cache_entries WHERE expires_at > ?",
                        (now_ts,),
                    )
                    row = cursor.fetchone()
                    key_count = row[0] if row else 0
            except Exception:
                key_count = 0

            total = self._hits + self._misses
            hit_rate = self._hits / total if total > 0 else 0.0
            return {
                "backend": self.backend_name,
                "key_count": key_count,
                "hit_count": self._hits,
                "miss_count": self._misses,
                "hit_rate": round(hit_rate, 4),
            }
