from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Awaitable, Callable, TypeVar

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from schulmanager_api.config import Settings, get_settings
from schulmanager_api.dependencies import (
    get_cache_store,
    get_provider,
    require_roles,
)
from schulmanager_api.models.schemas import (
    AbsenceItem,
    EventItem,
    ExamItem,
    GradeItem,
    GradeStats,
    HomeworkDoneRequest,
    HomeworkItem,
    LearningItem,
    LetterItem,
    MessageItem,
    MessageThread,
    PaymentItem,
    Role,
    ScheduleDay,
    Student,
)
from schulmanager_api.providers.base import SchulmanagerProvider
from schulmanager_api.services.grade_stats import compute_grade_stats
from schulmanager_api.services.ical import build_ics
from schulmanager_api.services.security import AuthPrincipal

router = APIRouter(prefix="/students", tags=["students"])

# Type alias that works with both memory and sqlite backends
CacheBackend = Any

T = TypeVar("T")

_READ_ROLES = (Role.ADMIN, Role.PARENT, Role.VIEWER)


def _key(principal: AuthPrincipal, student_id: str, scope: str, *parts: str) -> str:
    suffix = ":".join(parts)
    return f"{principal.account_id}:{student_id}:{scope}:{suffix}"


async def _cached(
    cache: CacheBackend,
    settings: Settings,
    key: str,
    ttl_seconds: int,
    force_refresh: bool,
    fetch: Callable[[], Awaitable[list[T]]],
) -> list[T]:
    """Return a cached list, or fetch + store it. Centralises the read/miss/write pattern."""
    if settings.cache_enabled and not force_refresh:
        cached = cache.get(key)
        if isinstance(cached, list):
            return cached
    data = await fetch()
    if settings.cache_enabled:
        cache.set(key, data, ttl_seconds)
    return data


@router.get("", response_model=list[Student])
async def list_students(
    principal: AuthPrincipal = Depends(require_roles(*_READ_ROLES)),
    provider: SchulmanagerProvider = Depends(get_provider),
) -> list[Student]:
    return await provider.get_students(principal.context)


@router.get("/{student_id}/schedule", response_model=list[ScheduleDay])
async def schedule(
    student_id: str,
    from_date: date | None = None,
    to_date: date | None = None,
    force_refresh: bool = False,
    principal: AuthPrincipal = Depends(require_roles(*_READ_ROLES)),
    provider: SchulmanagerProvider = Depends(get_provider),
    cache: CacheBackend = Depends(get_cache_store),
    settings: Settings = Depends(get_settings),
) -> list[ScheduleDay]:
    key = _key(principal, student_id, "schedule", str(from_date or "none"), str(to_date or "none"))
    return await _cached(
        cache, settings, key, settings.cache_ttl_schedule_seconds, force_refresh,
        lambda: provider.get_schedule(principal.context, student_id, from_date, to_date),
    )


@router.get("/{student_id}/homework", response_model=list[HomeworkItem])
async def homework(
    student_id: str,
    open_only: bool = False,
    force_refresh: bool = False,
    principal: AuthPrincipal = Depends(require_roles(*_READ_ROLES)),
    provider: SchulmanagerProvider = Depends(get_provider),
    cache: CacheBackend = Depends(get_cache_store),
    settings: Settings = Depends(get_settings),
) -> list[HomeworkItem]:
    key = _key(principal, student_id, "homework", f"open_only={open_only}")
    data = await _cached(
        cache, settings, key, settings.cache_ttl_homework_seconds, force_refresh,
        lambda: provider.get_homework(principal.context, student_id, open_only),
    )
    data = _apply_homework_overrides(cache, settings, principal, student_id, data)
    if open_only:
        data = [item for item in data if not item.done]
    return data


@router.patch("/{student_id}/homework/{homework_id}", response_model=HomeworkItem)
async def patch_homework_done(
    student_id: str,
    homework_id: str,
    body: HomeworkDoneRequest,
    principal: AuthPrincipal = Depends(require_roles(*_READ_ROLES)),
    provider: SchulmanagerProvider = Depends(get_provider),
    cache: CacheBackend = Depends(get_cache_store),
    settings: Settings = Depends(get_settings),
) -> HomeworkItem:
    """Mark a homework item done/undone *locally* (Schulmanager has no write-back API).

    The override is stored server-side (in the cache backend) and applied on every read, so it
    survives list-cache expiry and shows consistently for open_only True and False.
    """
    data = await provider.get_homework(principal.context, student_id, open_only=False)
    item = next((hw for hw in data if hw.id == homework_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Hausaufgabe nicht gefunden")

    _set_homework_override(cache, settings, principal, student_id, homework_id, body.done)
    # Invalidate both cached list variants so the next read reflects the change.
    if settings.cache_enabled:
        cache.delete_prefix(_key(principal, student_id, "homework", ""))

    return HomeworkItem(**{**item.model_dump(), "done": body.done})


@router.get("/{student_id}/exams", response_model=list[ExamItem])
async def exams(
    student_id: str,
    force_refresh: bool = False,
    principal: AuthPrincipal = Depends(require_roles(*_READ_ROLES)),
    provider: SchulmanagerProvider = Depends(get_provider),
    cache: CacheBackend = Depends(get_cache_store),
    settings: Settings = Depends(get_settings),
) -> list[ExamItem]:
    key = _key(principal, student_id, "exams")
    return await _cached(
        cache, settings, key, settings.cache_ttl_exams_seconds, force_refresh,
        lambda: provider.get_exams(principal.context, student_id),
    )


@router.get("/{student_id}/grades", response_model=list[GradeItem])
async def grades(
    student_id: str,
    force_refresh: bool = False,
    principal: AuthPrincipal = Depends(require_roles(*_READ_ROLES)),
    provider: SchulmanagerProvider = Depends(get_provider),
    cache: CacheBackend = Depends(get_cache_store),
    settings: Settings = Depends(get_settings),
) -> list[GradeItem]:
    key = _key(principal, student_id, "grades")
    return await _cached(
        cache, settings, key, settings.cache_ttl_grades_seconds, force_refresh,
        lambda: provider.get_grades(principal.context, student_id),
    )


@router.get("/{student_id}/grades/stats", response_model=GradeStats)
async def grade_stats(
    student_id: str,
    force_refresh: bool = False,
    principal: AuthPrincipal = Depends(require_roles(*_READ_ROLES)),
    provider: SchulmanagerProvider = Depends(get_provider),
    cache: CacheBackend = Depends(get_cache_store),
    settings: Settings = Depends(get_settings),
) -> GradeStats:
    key = _key(principal, student_id, "grades")
    data = await _cached(
        cache, settings, key, settings.cache_ttl_grades_seconds, force_refresh,
        lambda: provider.get_grades(principal.context, student_id),
    )
    return compute_grade_stats(data)


@router.get("/{student_id}/events", response_model=list[EventItem])
async def events(
    student_id: str,
    force_refresh: bool = False,
    principal: AuthPrincipal = Depends(require_roles(*_READ_ROLES)),
    provider: SchulmanagerProvider = Depends(get_provider),
    cache: CacheBackend = Depends(get_cache_store),
    settings: Settings = Depends(get_settings),
) -> list[EventItem]:
    key = _key(principal, student_id, "events")
    return await _cached(
        cache, settings, key, settings.cache_ttl_events_seconds, force_refresh,
        lambda: provider.get_events(principal.context, student_id),
    )


@router.get("/{student_id}/absences", response_model=list[AbsenceItem])
async def absences(
    student_id: str,
    force_refresh: bool = False,
    principal: AuthPrincipal = Depends(require_roles(*_READ_ROLES)),
    provider: SchulmanagerProvider = Depends(get_provider),
    cache: CacheBackend = Depends(get_cache_store),
    settings: Settings = Depends(get_settings),
) -> list[AbsenceItem]:
    key = _key(principal, student_id, "absences")
    return await _cached(
        cache, settings, key, settings.cache_ttl_absences_seconds, force_refresh,
        lambda: provider.get_absences(principal.context, student_id),
    )


@router.get("/{student_id}/messages", response_model=list[MessageItem])
async def messages(
    student_id: str,
    force_refresh: bool = False,
    principal: AuthPrincipal = Depends(require_roles(*_READ_ROLES)),
    provider: SchulmanagerProvider = Depends(get_provider),
    cache: CacheBackend = Depends(get_cache_store),
    settings: Settings = Depends(get_settings),
) -> list[MessageItem]:
    key = _key(principal, student_id, "messages")
    return await _cached(
        cache, settings, key, settings.cache_ttl_messages_seconds, force_refresh,
        lambda: provider.get_messages(principal.context, student_id),
    )


@router.get("/{student_id}/messages/{subscription_id}", response_model=MessageThread)
async def message_thread(
    student_id: str,
    subscription_id: str,
    force_refresh: bool = False,
    principal: AuthPrincipal = Depends(require_roles(*_READ_ROLES)),
    provider: SchulmanagerProvider = Depends(get_provider),
    cache: CacheBackend = Depends(get_cache_store),
    settings: Settings = Depends(get_settings),
) -> MessageThread:
    key = _key(principal, student_id, "thread", subscription_id)
    if settings.cache_enabled and not force_refresh:
        cached = cache.get(key)
        if isinstance(cached, MessageThread):
            return cached
    data = await provider.get_message_thread(principal.context, student_id, subscription_id)
    if settings.cache_enabled:
        cache.set(key, data, settings.cache_ttl_messages_seconds)
    return data


@router.get("/{student_id}/letters", response_model=list[LetterItem])
async def letters(
    student_id: str,
    force_refresh: bool = False,
    principal: AuthPrincipal = Depends(require_roles(*_READ_ROLES)),
    provider: SchulmanagerProvider = Depends(get_provider),
    cache: CacheBackend = Depends(get_cache_store),
    settings: Settings = Depends(get_settings),
) -> list[LetterItem]:
    """Elternbriefe / parent letters, with per-student read status."""
    key = _key(principal, student_id, "letters")
    return await _cached(
        cache, settings, key, settings.cache_ttl_messages_seconds, force_refresh,
        lambda: provider.get_letters(principal.context, student_id),
    )


@router.get("/{student_id}/payments", response_model=list[PaymentItem])
async def payments(
    student_id: str,
    force_refresh: bool = False,
    principal: AuthPrincipal = Depends(require_roles(*_READ_ROLES)),
    provider: SchulmanagerProvider = Depends(get_provider),
    cache: CacheBackend = Depends(get_cache_store),
    settings: Settings = Depends(get_settings),
) -> list[PaymentItem]:
    """Zahlungen / invoices with paid status."""
    key = _key(principal, student_id, "payments")
    return await _cached(
        cache, settings, key, settings.cache_ttl_exams_seconds, force_refresh,
        lambda: provider.get_payments(principal.context, student_id),
    )


@router.get("/{student_id}/learning", response_model=list[LearningItem])
async def learning(
    student_id: str,
    force_refresh: bool = False,
    principal: AuthPrincipal = Depends(require_roles(*_READ_ROLES)),
    provider: SchulmanagerProvider = Depends(get_provider),
    cache: CacheBackend = Depends(get_cache_store),
    settings: Settings = Depends(get_settings),
) -> list[LearningItem]:
    """Lernen / learning units (assignments & materials) with seen/done status."""
    key = _key(principal, student_id, "learning")
    return await _cached(
        cache, settings, key, settings.cache_ttl_exams_seconds, force_refresh,
        lambda: provider.get_learning(principal.context, student_id),
    )


@router.get("/{student_id}/calendar.ics")
async def calendar_ics(
    student_id: str,
    force_refresh: bool = False,
    horizon_days: int = 90,
    principal: AuthPrincipal = Depends(require_roles(*_READ_ROLES)),
    provider: SchulmanagerProvider = Depends(get_provider),
    cache: CacheBackend = Depends(get_cache_store),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Return an RFC 5545 .ics file combining schedule, exams, and events."""
    from datetime import date as DateType

    students = await provider.get_students(principal.context)
    student = next((s for s in students if s.id == student_id), None)
    student_name = f"{student.first_name} {student.last_name}" if student else student_id

    today = DateType.today()
    to_date = today + timedelta(days=max(horizon_days, 1))

    # Own cache key: the calendar's date window differs from the plain schedule GET's, so it must
    # not read that key. exams/events have no window and can reuse the shared keys.
    cal_key = _key(principal, student_id, "schedule", "cal", str(horizon_days))
    schedule_data = await _cached(
        cache, settings, cal_key, settings.cache_ttl_schedule_seconds, force_refresh,
        lambda: provider.get_schedule(principal.context, student_id, today, to_date),
    )
    exams_data = await _cached(
        cache, settings, _key(principal, student_id, "exams"), settings.cache_ttl_exams_seconds,
        force_refresh, lambda: provider.get_exams(principal.context, student_id),
    )
    events_data = await _cached(
        cache, settings, _key(principal, student_id, "events"), settings.cache_ttl_events_seconds,
        force_refresh, lambda: provider.get_events(principal.context, student_id),
    )

    ics_bytes = build_ics(
        student_name,
        [d.model_dump(mode="json") for d in schedule_data],
        [e.model_dump(mode="json") for e in exams_data],
        [e.model_dump(mode="json") for e in events_data],
        horizon_days=horizon_days,
        tz_name=settings.school_timezone,
    )

    return Response(
        content=ics_bytes,
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{student_id}.ics"'},
    )


# --------------------------------------------------------------------------- #
# Local homework done-status overrides (Schulmanager exposes no write-back API)
# --------------------------------------------------------------------------- #

def _override_key(principal: AuthPrincipal, student_id: str) -> str:
    return _key(principal, student_id, "hwdone")

# ~30 days; long enough that a "done" flag persists well beyond the list cache TTL.
_HW_OVERRIDE_TTL = 60 * 60 * 24 * 30


def _set_homework_override(
    cache: CacheBackend,
    settings: Settings,
    principal: AuthPrincipal,
    student_id: str,
    homework_id: str,
    done: bool,
) -> None:
    if not settings.cache_enabled:
        return
    key = _override_key(principal, student_id)
    overrides = cache.get(key)
    if not isinstance(overrides, dict):
        overrides = {}
    overrides = {**overrides, homework_id: done}
    cache.set(key, overrides, _HW_OVERRIDE_TTL)


def _apply_homework_overrides(
    cache: CacheBackend,
    settings: Settings,
    principal: AuthPrincipal,
    student_id: str,
    items: list[HomeworkItem],
) -> list[HomeworkItem]:
    if not settings.cache_enabled:
        return items
    overrides = cache.get(_override_key(principal, student_id))
    if not isinstance(overrides, dict) or not overrides:
        return items
    return [
        HomeworkItem(**{**hw.model_dump(), "done": overrides[hw.id]}) if hw.id in overrides else hw
        for hw in items
    ]
