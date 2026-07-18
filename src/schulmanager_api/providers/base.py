from __future__ import annotations

from datetime import date
from typing import Protocol

from schulmanager_api.models.schemas import (
    AbsenceItem,
    AuthRequest,
    EventItem,
    ExamItem,
    GradeItem,
    HomeworkItem,
    LearningItem,
    LetterItem,
    LoginContext,
    MessageItem,
    MessageThread,
    PaymentItem,
    ScheduleDay,
    Student,
)


class SchulmanagerProvider(Protocol):
    async def login(self, credentials: AuthRequest) -> LoginContext: ...

    async def get_students(self, context: LoginContext) -> list[Student]: ...

    async def get_schedule(
        self,
        context: LoginContext,
        student_id: str,
        from_date: date | None,
        to_date: date | None,
    ) -> list[ScheduleDay]: ...

    async def get_homework(
        self,
        context: LoginContext,
        student_id: str,
        open_only: bool,
    ) -> list[HomeworkItem]: ...

    async def get_exams(self, context: LoginContext, student_id: str) -> list[ExamItem]: ...

    async def get_grades(self, context: LoginContext, student_id: str) -> list[GradeItem]: ...

    async def get_events(self, context: LoginContext, student_id: str) -> list[EventItem]: ...

    async def get_absences(self, context: LoginContext, student_id: str) -> list[AbsenceItem]: ...

    async def get_messages(self, context: LoginContext, student_id: str) -> list[MessageItem]: ...

    async def get_message_thread(
        self, context: LoginContext, student_id: str, subscription_id: str
    ) -> MessageThread: ...

    async def get_letters(self, context: LoginContext, student_id: str) -> list[LetterItem]: ...

    async def get_payments(self, context: LoginContext, student_id: str) -> list[PaymentItem]: ...

    async def get_learning(self, context: LoginContext, student_id: str) -> list[LearningItem]: ...
