from __future__ import annotations

from threading import Lock

from schulmanager_api.models.schemas import (
    AbsenceItem,
    GradeItem,
    HomeworkItem,
    Lesson,
    LetterItem,
    MessageItem,
    ScheduleDay,
    WebhookEventType,
)
from schulmanager_api.services.webhooks import WebhookDispatcher


class _BoundedKeySet:
    """Insertion-ordered set with a hard cap; evicts the oldest keys when full.

    Prevents the 'seen' state from growing without bound for the process lifetime.
    """

    def __init__(self, max_size: int = 5000) -> None:
        self._max = max_size
        self._data: dict[str, None] = {}

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def add(self, key: str) -> None:
        if key in self._data:
            return
        self._data[key] = None
        while len(self._data) > self._max:
            self._data.pop(next(iter(self._data)))


class EventMonitor:
    """Tracks which items have already been seen so only genuinely new items emit events.

    On the *first* observation of a given (account, student, scope) the current items are
    seeded silently (no events) so a fresh registration / restart does not flood webhooks with
    the entire existing history. Subsequent observations emit only deltas.
    """

    def __init__(self, max_keys_per_scope: int = 5000) -> None:
        self._lock = Lock()
        self._max = max_keys_per_scope
        self._seen: dict[str, _BoundedKeySet] = {}
        self._primed: set[str] = set()

    def _collect_new(self, scope: str, keyed_items: list[tuple[str, object]]) -> list[object]:
        with self._lock:
            seen = self._seen.setdefault(scope, _BoundedKeySet(self._max))
            first_time = scope not in self._primed
            new_items: list[object] = []
            for key, item in keyed_items:
                if key in seen:
                    continue
                seen.add(key)
                if not first_time:
                    new_items.append(item)
            if first_time:
                self._primed.add(scope)
                return []
            return new_items

    def get_new_homework(self, account_id: str, student_id: str, items: list[HomeworkItem]) -> list[HomeworkItem]:
        scope = f"{account_id}:{student_id}:homework"
        keyed = [
            (f"{item.id}:{item.subject}:{item.due_date.isoformat()}:{item.done}", item)
            for item in items
        ]
        return self._collect_new(scope, keyed)  # type: ignore[return-value]

    def get_new_grades(self, account_id: str, student_id: str, items: list[GradeItem]) -> list[GradeItem]:
        scope = f"{account_id}:{student_id}:grades"
        keyed = [
            (
                f"{item.subject}:{item.grade}:{item.date.isoformat() if item.date else ''}:{item.comment or ''}",
                item,
            )
            for item in items
        ]
        return self._collect_new(scope, keyed)  # type: ignore[return-value]

    def get_new_absences(self, account_id: str, student_id: str, items: list[AbsenceItem]) -> list[AbsenceItem]:
        scope = f"{account_id}:{student_id}:absences"
        keyed = [(f"{item.id}:{item.date.isoformat()}", item) for item in items]
        return self._collect_new(scope, keyed)  # type: ignore[return-value]

    def get_new_messages(self, account_id: str, student_id: str, items: list[MessageItem]) -> list[MessageItem]:
        scope = f"{account_id}:{student_id}:messages"
        # Keyed by id + unread_count so a new incoming message in an existing thread re-emits.
        keyed = [(f"{item.id}:{item.unread_count}", item) for item in items]
        return self._collect_new(scope, keyed)  # type: ignore[return-value]

    def get_new_letters(self, account_id: str, student_id: str, items: list[LetterItem]) -> list[LetterItem]:
        scope = f"{account_id}:{student_id}:letters"
        keyed = [(f"{item.id}", item) for item in items]
        return self._collect_new(scope, keyed)  # type: ignore[return-value]

    def get_new_schedule_changes(
        self, account_id: str, student_id: str, schedule: list[ScheduleDay]
    ) -> list[tuple[ScheduleDay, Lesson]]:
        scope = f"{account_id}:{student_id}:schedule"
        keyed: list[tuple[str, tuple[ScheduleDay, Lesson]]] = []
        for day in schedule:
            for lesson in day.lessons:
                if lesson.change_type is None:
                    continue
                key = (
                    f"{day.date.isoformat()}:{lesson.start_time}:{lesson.subject}:{lesson.change_type.value}"
                )
                keyed.append((key, (day, lesson)))
        return self._collect_new(scope, keyed)  # type: ignore[return-value]


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
                {"account_id": account_id, "student_id": student_id, "item": item.model_dump(mode="json")},
            )
        return dispatched

    async def publish_grade_events(self, account_id: str, student_id: str, items: list[GradeItem]) -> int:
        new_items = self._monitor.get_new_grades(account_id, student_id, items)
        dispatched = 0
        for item in new_items:
            dispatched += await self._dispatcher.dispatch(
                WebhookEventType.GRADE_NEW,
                {"account_id": account_id, "student_id": student_id, "item": item.model_dump(mode="json")},
            )
        return dispatched

    async def publish_absence_events(self, account_id: str, student_id: str, items: list[AbsenceItem]) -> int:
        new_items = self._monitor.get_new_absences(account_id, student_id, items)
        dispatched = 0
        for item in new_items:
            dispatched += await self._dispatcher.dispatch(
                WebhookEventType.ABSENCE_NEW,
                {"account_id": account_id, "student_id": student_id, "item": item.model_dump(mode="json")},
            )
        return dispatched

    async def publish_message_events(self, account_id: str, student_id: str, items: list[MessageItem]) -> int:
        new_items = self._monitor.get_new_messages(account_id, student_id, items)
        dispatched = 0
        for item in new_items:
            dispatched += await self._dispatcher.dispatch(
                WebhookEventType.MESSAGE_NEW,
                {"account_id": account_id, "student_id": student_id, "item": item.model_dump(mode="json")},
            )
        return dispatched

    async def publish_letter_events(self, account_id: str, student_id: str, items: list[LetterItem]) -> int:
        new_items = self._monitor.get_new_letters(account_id, student_id, items)
        dispatched = 0
        for item in new_items:
            dispatched += await self._dispatcher.dispatch(
                WebhookEventType.LETTER_NEW,
                {"account_id": account_id, "student_id": student_id, "item": item.model_dump(mode="json")},
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
            {"account_id": account_id, "summary": summary},
        )
