from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe
from typing import Any

import jwt

from schulmanager_api.config import Settings
from schulmanager_api.models.schemas import LoginContext, Role, SessionInfo, Student
from schulmanager_api.services.auth_store import InMemoryAuthStore, RefreshSessionRecord


@dataclass(slots=True)
class AuthPrincipal:
    account_id: str
    email: str
    role: Role
    school_id: str | None
    context: LoginContext
    created_at: datetime
    expires_at: datetime


@dataclass(slots=True)
class TokenBundle:
    access_token: str
    refresh_token: str
    access_expires_at: datetime
    refresh_expires_at: datetime


class JWTAuthService:
    def __init__(self, settings: Settings, store: InMemoryAuthStore) -> None:
        self._settings = settings
        self._store = store

    def issue_tokens(self, context: LoginContext, role: Role) -> tuple[TokenBundle, SessionInfo]:
        now = datetime.now(timezone.utc)
        access_expires_at = now + timedelta(minutes=self._settings.access_token_ttl_minutes)
        refresh_expires_at = now + timedelta(days=self._settings.refresh_token_ttl_days)
        refresh_id = token_urlsafe(24)

        access_claims = {
            "type": "access",
            "sub": context.account_id,
            "email": context.email,
            "role": role.value,
            "school_id": context.school_id,
            "institution_id": context.institution_id,
            "user_id": context.user_id,
            "students": [student.model_dump(mode="json") for student in context.students],
            "iat": int(now.timestamp()),
            "exp": int(access_expires_at.timestamp()),
            "jti": token_urlsafe(16),
        }

        refresh_claims = {
            "type": "refresh",
            "sub": context.account_id,
            "email": context.email,
            "role": role.value,
            "rid": refresh_id,
            "context": context.model_dump(mode="json"),
            "iat": int(now.timestamp()),
            "exp": int(refresh_expires_at.timestamp()),
        }

        access_token = jwt.encode(
            access_claims,
            self._settings.jwt_secret,
            algorithm=self._settings.jwt_algorithm,
        )
        refresh_token = jwt.encode(
            refresh_claims,
            self._settings.jwt_secret,
            algorithm=self._settings.jwt_algorithm,
        )

        self._store.put_refresh_session(
            RefreshSessionRecord(
                refresh_id=refresh_id,
                account_id=context.account_id,
                email=context.email,
                role=role,
                context=context,
                created_at=now,
                expires_at=refresh_expires_at,
            )
        )

        session_info = SessionInfo(
            account_id=context.account_id,
            email=context.email,
            role=role,
            school_id=context.school_id,
            student_ids=[student.id for student in context.students],
            created_at=now,
            expires_at=access_expires_at,
        )

        return (
            TokenBundle(
                access_token=access_token,
                refresh_token=refresh_token,
                access_expires_at=access_expires_at,
                refresh_expires_at=refresh_expires_at,
            ),
            session_info,
        )

    def refresh_tokens(self, refresh_token: str) -> tuple[TokenBundle, SessionInfo]:
        claims = self._decode_token(refresh_token, expected_type="refresh")

        refresh_id = str(claims.get("rid") or "")
        if not refresh_id:
            raise ValueError("Refresh Token ungueltig")

        now = datetime.now(timezone.utc)
        consumed = self._store.consume_refresh_session(refresh_id, now)
        if consumed is None:
            raise ValueError("Refresh Token ungueltig oder bereits verwendet")

        context = consumed.context
        role = consumed.role

        new_bundle, session_info = self.issue_tokens(context=context, role=role)

        new_claims = self._decode_token(new_bundle.refresh_token, expected_type="refresh")
        new_refresh_id = str(new_claims.get("rid") or "")
        if new_refresh_id:
            self._store.mark_replaced(refresh_id, new_refresh_id)

        return new_bundle, session_info

    def decode_access_principal(self, token: str) -> AuthPrincipal:
        claims = self._decode_token(token, expected_type="access")
        account_id = str(claims.get("sub") or "")
        email = str(claims.get("email") or "")
        role = Role(str(claims.get("role") or Role.PARENT.value))

        students_raw = claims.get("students")
        if not isinstance(students_raw, list):
            raise ValueError("Access Token enthaelt keine gueltigen Schuelerdaten")

        students: list[Student] = []
        for raw in students_raw:
            if isinstance(raw, dict):
                students.append(Student.model_validate(raw))

        context = LoginContext(
            account_id=account_id,
            email=email,
            school_id=self._as_opt_str(claims.get("school_id")),
            institution_id=self._as_opt_int(claims.get("institution_id")),
            user_id=self._as_opt_int(claims.get("user_id")),
            students=students,
        )

        iat = int(claims.get("iat") or 0)
        exp = int(claims.get("exp") or 0)

        return AuthPrincipal(
            account_id=account_id,
            email=email,
            role=role,
            school_id=context.school_id,
            context=context,
            created_at=datetime.fromtimestamp(iat, tz=timezone.utc),
            expires_at=datetime.fromtimestamp(exp, tz=timezone.utc),
        )

    def revoke_account(self, account_id: str) -> int:
        return self._store.revoke_account(account_id)

    def decide_role(self, email: str) -> Role:
        if email.strip().lower() in self._settings.admin_emails:
            return Role.ADMIN
        return Role.PARENT

    def _decode_token(self, token: str, expected_type: str) -> dict[str, Any]:
        try:
            claims = jwt.decode(
                token,
                self._settings.jwt_secret,
                algorithms=[self._settings.jwt_algorithm],
                options={"require": ["exp", "iat", "sub", "type"]},
            )
        except jwt.PyJWTError as exc:  # pragma: no cover - depends on runtime token shape
            raise ValueError("Token ungueltig") from exc

        token_type = claims.get("type")
        if token_type != expected_type:
            raise ValueError("Falscher Tokentyp")
        return claims

    @staticmethod
    def _as_opt_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _as_opt_str(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text if text else None
