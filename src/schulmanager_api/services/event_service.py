from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

from schulmanager_api.models.schemas import AbsenceItem, GradeItem, HomeworkItem, Lesson, MessageItem, ScheduleDay, WebhookEventType
from schulmanager_api.services.webhooks import WebhookDispatcher


@dataclass(slots=True)
class EventCounters:
    dispatched: int = 0


class EventMonitor:
    def __init__(self) -> None:
        self._lock = Lock()
        self._seen_homework: set[str] = set()
        self._seen_grades: set[str] = set()
        self._seen_absences: set[str] = set()
        self._seen_messages: set[str] = set()
        self._seen_schedule_changes: set[str] = set()

    def get_new_homework(self, account_id: str, student_id: str, items: list[HomeworkItem]) -> list[HomeworkItem]:
        new_items: list[HomeworkItem] = []
        with self._lock:
            for item in items:
                key = f"{account_id}:{student_id}:{item.id}:{item.subject}:{item.due_date.isoformat()}"
                if key in self._seen_homework:
                    continue
                self._seen_homework.add(key)
                new_items.append(item)
        return new_items

    def get_new_grades(self, account_id: str, student_id: str, items: list[GradeItem]) -> list[GradeItem]:
        new_items: list[GradeItem] = []
        with self._lock:
            for item in items:
                date_part = item.date.isoformat() if item.date else ""
                key = f"{account_id}:{student_id}:{item.subject}:{item.grade}:{date_part}:{item.comment or ''}"
                if key in self._seen_grades:
                    continue
                self._seen_grades.add(key)
                new_items.append(item)
        return new_items

    def get_new_absences(self, account_id: str, student_id: str, items: list[AbsenceItem]) -> list[AbsenceItem]:
        new_items: list[AbsenceItem] = []
        with self._lock:
            for item in items:
                key = f"{account_id}:{student_id}:{item.id}:{item.date.isoformat()}"
                if key in self._seen_absences:
                    continue
                self._seen_absences.add(key)
                new_items.append(item)
        return new_items

    def get_new_messages(self, account_id: str, student_id: str, items: list[MessageItem]) -> list[MessageItem]:
        new_items: list[MessageItem] = []
        with self._lock:
            for item in items:
                key = f"{account_id}:{student_id}:{item.id}"
                if key in self._seen_messages:
                    continue
                self._seen_messages.add(key)
                new_items.append(item)
        return new_items

    def get_new_schedule_changes(
        self, account_id: str, student_id: str, schedule: list[ScheduleDay]
    ) -> list[tuple[ScheduleDay, Lesson]]:
        new_changes: list[tuple[ScheduleDay, Lesson]] = []
        with self._lock:
            for day in schedule:
                for lesson in day.lessons:
                    if lesson.change_type is None:
                        continue
                    key = (
                        f"{account_id}:{student_id}:{day.date.isoformat()}"
                        f":{lesson.start_time}:{lesson.subject}:{lesson.change_type.value}"
                    )
                    if key in self._seen_schedule_changes:
                        continue
                    self._seen_schedule_changes.add(key)
                    new_changes.append((day, lesson))
        return new_changes


class EventService:
    def __init__(self, monitor: EventMonitor, dispatcher: WebhookDispatcher) -> None:
        self._monitor = monitor
        self._dispatcher = dispatcher

    async def publish_homework_events(self, account_id: str, student_id: str, items: list[HomeworkItem]) -> int:
        new_items = self._monitor.get_new_homework(account_id, student_id, items)
        dispatched = 0
        for item in new_items:
            dispatched += await self._dispatcher.dispatch(
                WebhookEventType.HOMEWORK_NEW,
                {
                    "account_id": account_id,
                    "student_id": student_id,
                    "item": item.model_dump(mode="json"),
                },
            )
        return dispatched

    async def publish_grade_events(self, account_id: str, student_id: str, items: list[GradeItem]) -> int:
        new_items = self._monitor.get_new_grades(account_id, student_id, items)
        dispatched = 0
        for item in new_items:
            dispatched += await self._dispatcher.dispatch(
                WebhookEventType.GRADE_NEW,
                {
                    "account_id": account_id,
                    "student_id": student_id,
                    "item": item.model_dump(mode="json"),
                },
            )
        return dispatched

    async def publish_absence_events(self, account_id: str, student_id: str, items: list[AbsenceItem]) -> int:
        new_items = self._monitor.get_new_absences(account_id, student_id, items)
        dispatched = 0
        for item in new_items:
            dispatched += await self._dispatcher.dispatch(
                WebhookEventType.ABSENCE_NEW,
                {
                    "account_id": account_id,
                    "student_id": student_id,
                    "item": item.model_dump(mode="json"),
                },
            )
        return dispatched

    async def publish_message_events(self, account_id: str, student_id: str, items: list[MessageItem]) -> int:
        new_items = self._monitor.get_new_messages(account_id, student_id, items)
        dispatched = 0
        for item in new_items:
            dispatched += await self._dispatcher.dispatch(
                WebhookEventType.MESSAGE_NEW,
                {
                    "account_id": account_id,
                    "student_id": student_id,
                    "item": item.model_dump(mode="json"),
                },
            )
        return dispatched

    async def publish_schedule_change_events(
        self, account_id: str, student_id: str, schedule: list[ScheduleDay]
    ) -> int:
        new_changes = self._monitor.get_new_schedule_changes(account_id, student_id, schedule)
        dispatched = 0
        for day, lesson in new_changes:
            dispatched += await self._dispatcher.dispatch(
                WebhookEventType.SCHEDULE_CHANGE,
                {
                    "account_id": account_id,
                    "student_id": student_id,
                    "date": day.date.isoformat(),
                    "lesson": lesson.model_dump(mode="json"),
                },
            )
        return dispatched

    async def publish_sync_completed(self, account_id: str, summary: dict[str, int]) -> int:
        return await self._dispatcher.dispatch(
            WebhookEventType.SYNC_COMPLETED,
            {
                "account_id": account_id,
                "summary": summary,
            },
        )
