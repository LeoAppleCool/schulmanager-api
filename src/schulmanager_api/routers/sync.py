from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from schulmanager_api.config import Settings, get_settings
from schulmanager_api.dependencies import get_cache_store, get_event_service, get_provider, require_roles
from schulmanager_api.models.schemas import Role, SyncRefreshRequest, SyncRefreshResult
from schulmanager_api.providers.base import SchulmanagerProvider
from schulmanager_api.services import metrics_store
from schulmanager_api.services.event_service import EventService
from schulmanager_api.services.security import AuthPrincipal

router = APIRouter(prefix="/sync", tags=["sync"])


@router.post("/refresh", response_model=SyncRefreshResult)
async def refresh_all(
    payload: SyncRefreshRequest,
    principal: AuthPrincipal = Depends(require_roles(Role.ADMIN, Role.PARENT, Role.VIEWER)),
    provider: SchulmanagerProvider = Depends(get_provider),
    cache: Any = Depends(get_cache_store),
    event_service: EventService = Depends(get_event_service),
    settings: Settings = Depends(get_settings),
) -> SyncRefreshResult:
    try:
        return await _run_sync(payload, principal, provider, cache, event_service, settings)
    except Exception:
        metrics_store.syncs_total.labels(status="error").inc()
        raise


async def _run_sync(
    payload: SyncRefreshRequest,
    principal: AuthPrincipal,
    provider: SchulmanagerProvider,
    cache: Any,
    event_service: EventService,
    settings: Settings,
) -> SyncRefreshResult:
    schedule_days = 0
    homework_items = 0
    exams_count = 0
    grades_count = 0
    events_count = 0
    absences_count = 0
    messages_count = 0
    letters_count = 0
    triggered_events = 0

    for student in principal.context.students:
        sid = student.id

        if payload.force_refresh and settings.cache_enabled:
            cache.delete_prefix(f"{principal.account_id}:{sid}:")

        if payload.schedule:
            schedule = await provider.get_schedule(principal.context, sid, None, None)
            schedule_days += len(schedule)
            if settings.cache_enabled:
                cache.set(f"{principal.account_id}:{sid}:schedule:none:none", schedule, settings.cache_ttl_schedule_seconds)

        if payload.homework:
            homework = await provider.get_homework(principal.context, sid, open_only=False)
            homework_items += len(homework)
            triggered_events += await event_service.publish_homework_events(principal.account_id, sid, homework)
            if settings.cache_enabled:
                cache.set(f"{principal.account_id}:{sid}:homework:open_only=False", homework, settings.cache_ttl_homework_seconds)

        if payload.exams:
            exams = await provider.get_exams(principal.context, sid)
            exams_count += len(exams)
            if settings.cache_enabled:
                cache.set(f"{principal.account_id}:{sid}:exams:", exams, settings.cache_ttl_exams_seconds)

        if payload.grades:
            grades = await provider.get_grades(principal.context, sid)
            grades_count += len(grades)
            triggered_events += await event_service.publish_grade_events(principal.account_id, sid, grades)
            if settings.cache_enabled:
                cache.set(f"{principal.account_id}:{sid}:grades:", grades, settings.cache_ttl_grades_seconds)

        if payload.events:
            events = await provider.get_events(principal.context, sid)
            events_count += len(events)
            if settings.cache_enabled:
                cache.set(f"{principal.account_id}:{sid}:events:", events, settings.cache_ttl_events_seconds)

        if payload.absences:
            absence_list = await provider.get_absences(principal.context, sid)
            absences_count += len(absence_list)
            triggered_events += await event_service.publish_absence_events(principal.account_id, sid, absence_list)
            if settings.cache_enabled:
                cache.set(f"{principal.account_id}:{sid}:absences:", absence_list, settings.cache_ttl_absences_seconds)

        if payload.messages:
            message_list = await provider.get_messages(principal.context, sid)
            messages_count += len(message_list)
            triggered_events += await event_service.publish_message_events(principal.account_id, sid, message_list)
            if settings.cache_enabled:
                cache.set(f"{principal.account_id}:{sid}:messages:", message_list, settings.cache_ttl_messages_seconds)

        if payload.letters:
            letter_list = await provider.get_letters(principal.context, sid)
            letters_count += len(letter_list)
            triggered_events += await event_service.publish_letter_events(principal.account_id, sid, letter_list)
            if settings.cache_enabled:
                cache.set(f"{principal.account_id}:{sid}:letters:", letter_list, settings.cache_ttl_messages_seconds)

    summary = {
        "students_processed": len(principal.context.students),
        "schedule_days": schedule_days,
        "homework_items": homework_items,
        "exams": exams_count,
        "grades": grades_count,
        "events": events_count,
        "absences": absences_count,
        "messages": messages_count,
        "letters": letters_count,
    }
    triggered_events += await event_service.publish_sync_completed(principal.account_id, summary)
    metrics_store.syncs_total.labels(status="success").inc()

    return SyncRefreshResult(
        students_processed=len(principal.context.students),
        schedule_days=schedule_days,
        homework_items=homework_items,
        exams=exams_count,
        grades=grades_count,
        events=events_count,
        absences=absences_count,
        messages=messages_count,
        letters=letters_count,
        triggered_events=triggered_events,
    )
