from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from threading import Lock

from schulmanager_api.models.schemas import LoginContext, Role


@dataclass(slots=True)
class RefreshSessionRecord:
    refresh_id: str
    account_id: str
    email: str
    role: Role
    context: LoginContext
    created_at: datetime
    expires_at: datetime
    revoked: bool = False
    replaced_by: str | None = None


class InMemoryAuthStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._refresh_sessions: dict[str, RefreshSessionRecord] = {}

    def put_refresh_session(self, record: RefreshSessionRecord) -> None:
        with self._lock:
            self._refresh_sessions[record.refresh_id] = record

    def consume_refresh_session(self, refresh_id: str, now: datetime) -> RefreshSessionRecord | None:
        with self._lock:
            record = self._refresh_sessions.get(refresh_id)
            if record is None:
                return None
            if record.revoked or record.expires_at <= now:
                self._refresh_sessions.pop(refresh_id, None)
                return None
            record.revoked = True
            return record

    def mark_replaced(self, refresh_id: str, new_refresh_id: str) -> None:
        with self._lock:
            record = self._refresh_sessions.get(refresh_id)
            if record is None:
                return
            record.replaced_by = new_refresh_id

    def revoke_account(self, account_id: str) -> int:
        revoked = 0
        with self._lock:
            for record in self._refresh_sessions.values():
                if record.account_id == account_id and not record.revoked:
                    record.revoked = True
                    revoked += 1
        return revoked
