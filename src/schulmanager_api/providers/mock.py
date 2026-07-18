from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from fastapi import HTTPException

from schulmanager_api.models.schemas import (
    AbsenceItem,
    AuthRequest,
    EventItem,
    ExamItem,
    GradeItem,
    HomeworkItem,
    LearningItem,
    Lesson,
    LessonChangeType,
    LetterItem,
    LoginContext,
    MessageItem,
    MessageThread,
    PaymentItem,
    ScheduleDay,
    Student,
    ThreadMessage,
)


class MockSchulmanagerProvider:
    """Demo provider with static data so the API is directly usable."""

    async def login(self, credentials: AuthRequest) -> LoginContext:
        students = [
            Student(
                id="stu_001",
                first_name="Max",
                last_name="Mustermann",
                class_name="10a",
                school_name="Muster-Gymnasium",
            ),
            Student(
                id="stu_002",
                first_name="Lena",
                last_name="Mustermann",
                class_name="7b",
                school_name="Muster-Gymnasium",
            ),
        ]
        return LoginContext(
            account_id=f"acc_{credentials.email.lower().replace('@', '_').replace('.', '_')}",
            email=credentials.email,
            school_id=credentials.school_id,
            students=students,
        )

    async def get_students(self, context: LoginContext) -> list[Student]:
        return context.students

    async def get_schedule(
        self,
        context: LoginContext,
        student_id: str,
        from_date: date | None,
        to_date: date | None,
    ) -> list[ScheduleDay]:
        self._ensure_student(context, student_id)

        start = from_date or date.today()
        end = to_date or (start + timedelta(days=2))
        day_count = max((end - start).days + 1, 1)

        days: list[ScheduleDay] = []
        for i in range(day_count):
            current_day = start + timedelta(days=i)
            days.append(
                ScheduleDay(
                    date=current_day,
                    lessons=[
                        Lesson(start_time="08:00", end_time="08:45", subject="Mathe", room="A201", teacher="Herr Koch"),
                        Lesson(start_time="08:50", end_time="09:35", subject="Deutsch", room="A105", teacher="Frau Adler"),
                        Lesson(
                            start_time="09:55",
                            end_time="10:40",
                            subject="Biologie",
                            room="Lab1",
                            teacher="Frau Weber",
                            change_type=LessonChangeType.SUBSTITUTION,
                            note="Vertretung durch Herrn Mayer",
                        ),
                    ],
                )
            )

        return days

    async def get_homework(
        self,
        context: LoginContext,
        student_id: str,
        open_only: bool,
    ) -> list[HomeworkItem]:
        self._ensure_student(context, student_id)
        items = [
            HomeworkItem(id="hw_001", subject="Mathe", text="Seite 42, Aufgaben 1-4", due_date=date.today() + timedelta(days=1), done=False),
            HomeworkItem(id="hw_002", subject="Englisch", text="Vokabeltest vorbereiten", due_date=date.today() + timedelta(days=2), done=True),
            HomeworkItem(id="hw_003", subject="Geschichte", text="Kapitel 5 lesen und zusammenfassen", due_date=date.today() + timedelta(days=3), done=False),
        ]
        if open_only:
            return [item for item in items if not item.done]
        return items

    async def get_exams(self, context: LoginContext, student_id: str) -> list[ExamItem]:
        self._ensure_student(context, student_id)
        return [
            ExamItem(id="exam_001", subject="Biologie", topic="Zellaufbau", date=date.today() + timedelta(days=5)),
            ExamItem(id="exam_002", subject="Geschichte", topic="Weimarer Republik", date=date.today() + timedelta(days=11)),
        ]

    async def get_grades(self, context: LoginContext, student_id: str) -> list[GradeItem]:
        self._ensure_student(context, student_id)
        return [
            GradeItem(subject="Mathe", grade="2", weight=1.0, date=date.today() - timedelta(days=60), comment="Kurzkontrolle"),
            GradeItem(subject="Mathe", grade="2+", weight=1.0, date=date.today() - timedelta(days=30), comment="Klassenarbeit"),
            GradeItem(subject="Mathe", grade="1-", weight=1.5, date=date.today() - timedelta(days=4), comment="Muendlich"),
            GradeItem(subject="Deutsch", grade="1-", weight=1.5, date=date.today() - timedelta(days=14), comment="Aufsatz"),
            GradeItem(subject="Deutsch", grade="2", weight=1.0, date=date.today() - timedelta(days=5), comment="Diktat"),
            GradeItem(subject="Biologie", grade="3+", weight=1.0, date=date.today() - timedelta(days=7), comment="Muendlich"),
        ]

    async def get_events(self, context: LoginContext, student_id: str) -> list[EventItem]:
        self._ensure_student(context, student_id)
        now = datetime.now(timezone.utc)
        return [
            EventItem(
                id="ev_001",
                title="Elternabend",
                start=datetime.combine(date.today() + timedelta(days=3), time(18, 0), tzinfo=timezone.utc),
                end=datetime.combine(date.today() + timedelta(days=3), time(19, 30), tzinfo=timezone.utc),
                location="Aula",
                description="Informationen zur Klassenfahrt",
            ),
            EventItem(
                id="ev_002",
                title="Schulfest",
                start=now + timedelta(days=15),
                end=now + timedelta(days=15, hours=4),
                location="Schulhof",
                description="Sommerfest mit AG-Staenden",
            ),
        ]

    async def get_absences(self, context: LoginContext, student_id: str) -> list[AbsenceItem]:
        self._ensure_student(context, student_id)
        return [
            AbsenceItem(
                id="abs_001",
                date=date.today() - timedelta(days=10),
                periods=["1", "2"],
                reason="Krankheit",
                excused=True,
            ),
            AbsenceItem(
                id="abs_002",
                date=date.today() - timedelta(days=5),
                periods=["3"],
                reason="Arzttermin",
                excused=True,
            ),
            AbsenceItem(
                id="abs_003",
                date=date.today() - timedelta(days=2),
                periods=["5", "6"],
                reason=None,
                excused=False,
            ),
        ]

    async def get_messages(self, context: LoginContext, student_id: str) -> list[MessageItem]:
        self._ensure_student(context, student_id)
        now = datetime.now(timezone.utc)
        return [
            MessageItem(
                id="msg_001",
                sender="Frau Adler",
                subject="Ausflug naechste Woche",
                body_preview="Liebe Eltern, bitte denken Sie daran, die Einverstaendniserklaerung...",
                date=now - timedelta(days=2),
                read=False,
                unread_count=1,
            ),
            MessageItem(
                id="msg_002",
                sender="Schulleitung",
                subject="Informationen zum Schuljahresende",
                body_preview="Sehr geehrte Eltern, hiermit moechten wir Sie ueber die Termine...",
                date=now - timedelta(days=7),
                read=True,
                unread_count=0,
            ),
        ]

    async def get_message_thread(
        self, context: LoginContext, student_id: str, subscription_id: str
    ) -> MessageThread:
        self._ensure_student(context, student_id)
        now = datetime.now(timezone.utc)
        return MessageThread(
            subscription_id=subscription_id,
            subject="Ausflug naechste Woche",
            messages=[
                ThreadMessage(
                    id="tmsg_001",
                    sender="Frau Adler",
                    text="Liebe Eltern, bitte denken Sie daran, die Einverstaendniserklaerung mitzugeben.",
                    date=now - timedelta(days=2, hours=3),
                    has_attachments=True,
                ),
                ThreadMessage(
                    id="tmsg_002",
                    sender="Max Mustermann (Elternteil)",
                    text="Vielen Dank fuer die Info, ist erledigt!",
                    date=now - timedelta(days=2, hours=1),
                ),
            ],
        )

    async def get_letters(self, context: LoginContext, student_id: str) -> list[LetterItem]:
        self._ensure_student(context, student_id)
        now = datetime.now(timezone.utc)
        return [
            LetterItem(
                id="letter_001",
                title="Elternbrief: Klassenfahrt Klasse 10",
                date=now - timedelta(days=1),
                read=False,
                sender="Klassenleitung 10a",
                requires_confirmation=True,
                attachment_count=1,
            ),
            LetterItem(
                id="letter_002",
                title="Infobrief: Neue Mensa-Zeiten",
                date=now - timedelta(days=9),
                read=True,
                sender="Schulleitung",
                requires_confirmation=False,
                attachment_count=0,
            ),
        ]

    async def get_payments(self, context: LoginContext, student_id: str) -> list[PaymentItem]:
        self._ensure_student(context, student_id)
        return [
            PaymentItem(
                id="inv_001",
                title="Klassenfahrt Berlin",
                amount=120.0,
                paid_amount=0.0,
                paid=False,
                due_date=date.today() + timedelta(days=10),
                date=date.today() - timedelta(days=4),
                invoice_number="2026-042",
            ),
            PaymentItem(
                id="inv_002",
                title="Kopiergeld",
                amount=15.0,
                paid_amount=15.0,
                paid=True,
                due_date=date.today() - timedelta(days=20),
                date=date.today() - timedelta(days=40),
                invoice_number="2026-021",
            ),
        ]

    async def get_learning(self, context: LoginContext, student_id: str) -> list[LearningItem]:
        self._ensure_student(context, student_id)
        now = datetime.now(timezone.utc)
        return [
            LearningItem(
                id="unit_001",
                subject="Digitale Bildung",
                title="Arbeitsblatt: Tabellenkalkulation",
                published=now - timedelta(days=1),
                seen=False,
                done=False,
            ),
            LearningItem(
                id="unit_002",
                subject="Englisch",
                title="Vocab Unit 5",
                published=now - timedelta(days=6),
                seen=True,
                done=True,
            ),
        ]

    def logout(self, account_id: str) -> None:
        """No-op for the mock provider (no server-side session)."""

    def _ensure_student(self, context: LoginContext, student_id: str) -> None:
        if student_id not in {student.id for student in context.students}:
            raise HTTPException(status_code=404, detail="Student nicht gefunden")
