from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Union

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from schulmanager_api.config import Settings, get_settings
from schulmanager_api.dependencies import (
    get_cache_store,
    get_current_principal,
    get_event_service,
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
    MessageItem,
    Role,
    ScheduleDay,
    Student,
)
from schulmanager_api.providers.base import SchulmanagerProvider
from schulmanager_api.services.cache import InMemoryTTLCache
from schulmanager_api.services.event_service import EventService
from schulmanager_api.services.grade_stats import compute_grade_stats
from schulmanager_api.services.ical import build_ics
from schulmanager_api.services.security import AuthPrincipal

router = APIRouter(prefix="/students", tags=["students"])

# Type alias that works with both memory and sqlite backends
CacheBackend = Any


def _cache_get_or_set(
    cache: CacheBackend,
    key: str,
    value: Any | None,
    ttl_seconds: int,
) -> Any | None:
    if value is not None:
        cache.set(key, value, ttl_seconds)
    return cache.get(key)


def _key(principal: AuthPrincipal, student_id: str, scope: str, *parts: str) -> str:
    suffix = ":".join(parts)
    return f"{principal.account_id}:{student_id}:{scope}:{suffix}"


@router.get("", response_model=list[Student])
async def list_students(
    principal: AuthPrincipal = Depends(require_roles(Role.ADMIN, Role.PARENT, Role.VIEWER)),
    provider: SchulmanagerProvider = Depends(get_provider),
) -> list[Student]:
    return await provider.get_students(principal.context)


@router.get("/{student_id}/schedule", response_model=list[ScheduleDay])
async def schedule(
    student_id: str,
    from_date: date | None = None,
    to_date: date | None = None,
    force_refresh: bool = False,
    principal: AuthPrincipal = Depends(require_roles(Role.ADMIN, Role.PARENT, Role.VIEWER)),
    provider: SchulmanagerProvider = Depends(get_provider),
    cache: CacheBackend = Depends(get_cache_store),
    settings: Settings = Depends(get_settings),
    event_service: EventService = Depends(get_event_service),
) -> list[ScheduleDay]:
    cache_key = _key(
        principal,
        student_id,
        "schedule",
        str(from_date or "none"),
        str(to_date or "none"),
    )

    if settings.cache_enabled and not force_refresh:
        cached = cache.get(cache_key)
        if isinstance(cached, list):
            return cached

    data = await provider.get_schedule(principal.context, student_id, from_date, to_date)
    if settings.cache_enabled:
        _cache_get_or_set(cache, cache_key, data, settings.cache_ttl_schedule_seconds)
    await event_service.publish_schedule_change_events(principal.account_id, student_id, data)
    return data


@router.get("/{student_id}/homework", response_model=list[HomeworkItem])
async def homework(
    student_id: str,
    open_only: bool = False,
    force_refresh: bool = False,
    principal: AuthPrincipal = Depends(require_roles(Role.ADMIN, Role.PARENT, Role.VIEWER)),
    provider: SchulmanagerProvider = Depends(get_provider),
    cache: CacheBackend = Depends(get_cache_store),
    event_service: EventService = Depends(get_event_service),
    settings: Settings = Depends(get_settings),
) -> list[HomeworkItem]:
    cache_key = _key(principal, student_id, "homework", f"open_only={open_only}")

    data: list[HomeworkItem]
    if settings.cache_enabled and not force_refresh:
        cached = cache.get(cache_key)
        if isinstance(cached, list):
            data = cached
        else:
            data = await provider.get_homework(principal.context, student_id, open_only)
            cache.set(cache_key, data, settings.cache_ttl_homework_seconds)
    else:
        data = await provider.get_homework(principal.context, student_id, open_only)
        if settings.cache_enabled:
            cache.set(cache_key, data, settings.cache_ttl_homework_seconds)

    await event_service.publish_homework_events(principal.account_id, student_id, data)
    return data


@router.patch("/{student_id}/homework/{homework_id}", response_model=HomeworkItem)
async def patch_homework_done(
    student_id: str,
    homework_id: str,
    body: HomeworkDoneRequest,
    principal: AuthPrincipal = Depends(require_roles(Role.ADMIN, Role.PARENT, Role.VIEWER)),
    provider: SchulmanagerProvider = Depends(get_provider),
    cache: CacheBackend = Depends(get_cache_store),
    settings: Settings = Depends(get_settings),
) -> HomeworkItem:
    """Update local done-status for a homework item (does NOT write back to Schulmanager)."""
    # Fetch current homework list (from cache or provider)
    cache_key = _key(principal, student_id, "homework", "open_only=False")
    data: list[HomeworkItem] | None = None
    if settings.cache_enabled:
        cached = cache.get(cache_key)
        if isinstance(cached, list):
            data = cached

    if data is None:
        data = await provider.get_homework(principal.context, student_id, open_only=False)

    # Find the item
    item = next((hw for hw in data if hw.id == homework_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Hausaufgabe nicht gefunden")

    # Update done status in the cached list
    updated_data = [
        HomeworkItem(**{**hw.model_dump(), "done": body.done}) if hw.id == homework_id else hw
        for hw in data
    ]
    if settings.cache_enabled:
        cache.set(cache_key, updated_data, settings.cache_ttl_homework_seconds)

    return HomeworkItem(**{**item.model_dump(), "done": body.done})


@router.get("/{student_id}/exams", response_model=list[ExamItem])
async def exams(
    student_id: str,
    force_refresh: bool = False,
    principal: AuthPrincipal = Depends(require_roles(Role.ADMIN, Role.PARENT, Role.VIEWER)),
    provider: SchulmanagerProvider = Depends(get_provider),
    cache: CacheBackend = Depends(get_cache_store),
    settings: Settings = Depends(get_settings),
) -> list[ExamItem]:
    cache_key = _key(principal, student_id, "exams")

    if settings.cache_enabled and not force_refresh:
        cached = cache.get(cache_key)
        if isinstance(cached, list):
            return cached

    data = await provider.get_exams(principal.context, student_id)
    if settings.cache_enabled:
        cache.set(cache_key, data, settings.cache_ttl_exams_seconds)
    return data


@router.get("/{student_id}/grades", response_model=list[GradeItem])
async def grades(
    student_id: str,
    force_refresh: bool = False,
    principal: AuthPrincipal = Depends(require_roles(Role.ADMIN, Role.PARENT, Role.VIEWER)),
    provider: SchulmanagerProvider = Depends(get_provider),
    cache: CacheBackend = Depends(get_cache_store),
    event_service: EventService = Depends(get_event_service),
    settings: Settings = Depends(get_settings),
) -> list[GradeItem]:
    cache_key = _key(principal, student_id, "grades")

    data: list[GradeItem]
    if settings.cache_enabled and not force_refresh:
        cached = cache.get(cache_key)
        if isinstance(cached, list):
            data = cached
        else:
            data = await provider.get_grades(principal.context, student_id)
            cache.set(cache_key, data, settings.cache_ttl_grades_seconds)
    else:
        data = await provider.get_grades(principal.context, student_id)
        if settings.cache_enabled:
            cache.set(cache_key, data, settings.cache_ttl_grades_seconds)

    await event_service.publish_grade_events(principal.account_id, student_id, data)
    return data


@router.get("/{student_id}/grades/stats", response_model=GradeStats)
async def grade_stats(
    student_id: str,
    force_refresh: bool = False,
    principal: AuthPrincipal = Depends(require_roles(Role.ADMIN, Role.PARENT, Role.VIEWER)),
    provider: SchulmanagerProvider = Depends(get_provider),
    cache: CacheBackend = Depends(get_cache_store),
    settings: Settings = Depends(get_settings),
) -> GradeStats:
    cache_key = _key(principal, student_id, "grades")

    data: list[GradeItem]
    if settings.cache_enabled and not force_refresh:
        cached = cache.get(cache_key)
        if isinstance(cached, list):
            data = cached
        else:
            data = await provider.get_grades(principal.context, student_id)
            cache.set(cache_key, data, settings.cache_ttl_grades_seconds)
    else:
        data = await provider.get_grades(principal.context, student_id)
        if settings.cache_enabled:
            cache.set(cache_key, data, settings.cache_ttl_grades_seconds)

    return compute_grade_stats(data)


@router.get("/{student_id}/events", response_model=list[EventItem])
async def events(
    student_id: str,
    force_refresh: bool = False,
    principal: AuthPrincipal = Depends(require_roles(Role.ADMIN, Role.PARENT, Role.VIEWER)),
    provider: SchulmanagerProvider = Depends(get_provider),
    cache: CacheBackend = Depends(get_cache_store),
    settings: Settings = Depends(get_settings),
) -> list[EventItem]:
    cache_key = _key(principal, student_id, "events")

    if settings.cache_enabled and not force_refresh:
        cached = cache.get(cache_key)
        if isinstance(cached, list):
            return cached

    data = await provider.get_events(principal.context, student_id)
    if settings.cache_enabled:
        cache.set(cache_key, data, settings.cache_ttl_events_seconds)
    return data


@router.get("/{student_id}/absences", response_model=list[AbsenceItem])
async def absences(
    student_id: str,
    force_refresh: bool = False,
    principal: AuthPrincipal = Depends(require_roles(Role.ADMIN, Role.PARENT, Role.VIEWER)),
    provider: SchulmanagerProvider = Depends(get_provider),
    cache: CacheBackend = Depends(get_cache_store),
    event_service: EventService = Depends(get_event_service),
    settings: Settings = Depends(get_settings),
) -> list[AbsenceItem]:
    cache_key = _key(principal, student_id, "absences")

    data: list[AbsenceItem]
    if settings.cache_enabled and not force_refresh:
        cached = cache.get(cache_key)
        if isinstance(cached, list):
            data = cached
        else:
            data = await provider.get_absences(principal.context, student_id)
            cache.set(cache_key, data, settings.cache_ttl_absences_seconds)
    else:
        data = await provider.get_absences(principal.context, student_id)
        if settings.cache_enabled:
            cache.set(cache_key, data, settings.cache_ttl_absences_seconds)

    await event_service.publish_absence_events(principal.account_id, student_id, data)
    return data


@router.get("/{student_id}/messages", response_model=list[MessageItem])
async def messages(
    student_id: str,
    force_refresh: bool = False,
    principal: AuthPrincipal = Depends(require_roles(Role.ADMIN, Role.PARENT, Role.VIEWER)),
    provider: SchulmanagerProvider = Depends(get_provider),
    cache: CacheBackend = Depends(get_cache_store),
    event_service: EventService = Depends(get_event_service),
    settings: Settings = Depends(get_settings),
) -> list[MessageItem]:
    cache_key = _key(principal, student_id, "messages")

    data: list[MessageItem]
    if settings.cache_enabled and not force_refresh:
        cached = cache.get(cache_key)
        if isinstance(cached, list):
            data = cached
        else:
            data = await provider.get_messages(principal.context, student_id)
            cache.set(cache_key, data, settings.cache_ttl_messages_seconds)
    else:
        data = await provider.get_messages(principal.context, student_id)
        if settings.cache_enabled:
            cache.set(cache_key, data, settings.cache_ttl_messages_seconds)

    await event_service.publish_message_events(principal.account_id, student_id, data)
    return data


@router.get("/{student_id}/calendar.ics")
async def calendar_ics(
    student_id: str,
    force_refresh: bool = False,
    horizon_days: int = 90,
    principal: AuthPrincipal = Depends(require_roles(Role.ADMIN, Role.PARENT, Role.VIEWER)),
    provider: SchulmanagerProvider = Depends(get_provider),
    cache: CacheBackend = Depends(get_cache_store),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Return a RFC 5545 .ics file combining schedule, exams, and events."""
    from datetime import date as DateType

    students = await provider.get_students(principal.context)
    student = next((s for s in students if s.id == student_id), None)
    student_name = f"{student.first_name} {student.last_name}" if student else student_id

    today = DateType.today()
    to_date = today + timedelta(days=horizon_days)

    def get_cached(scope: str) -> list | None:
        if not settings.cache_enabled or force_refresh:
            return None
        val = cache.get(f"{principal.account_id}:{student_id}:{scope}:")
        return val if isinstance(val, list) else None

    schedule_data = get_cached("schedule") or await provider.get_schedule(
        principal.context, student_id, today, to_date
    )
    exams_data = get_cached("exams") or await provider.get_exams(principal.context, student_id)
    events_data = get_cached("events") or await provider.get_events(principal.context, student_id)

    schedule_dicts = [d.model_dump(mode="json") for d in schedule_data]
    exams_dicts = [e.model_dump(mode="json") for e in exams_data]
    events_dicts = [e.model_dump(mode="json") for e in events_data]

    ics_bytes = build_ics(
        student_name,
        schedule_dicts,
        exams_dicts,
        events_dicts,
        horizon_days=horizon_days,
    )

    return Response(
        content=ics_bytes,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{student_id}.ics"',
        },
    )
