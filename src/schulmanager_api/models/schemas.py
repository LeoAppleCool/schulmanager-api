from __future__ import annotations

from datetime import date as DateType, datetime
from enum import Enum

from pydantic import AnyHttpUrl, BaseModel, Field


class Role(str, Enum):
    ADMIN = "admin"
    PARENT = "parent"
    VIEWER = "viewer"


class LessonChangeType(str, Enum):
    CANCELLATION = "cancellation"
    SUBSTITUTION = "substitution"
    ROOM_CHANGE = "room_change"
    EXAM = "exam"
    INFO = "info"


class AuthRequest(BaseModel):
    email: str = Field(min_length=3)
    password: str = Field(min_length=1)
    school_id: str | None = None
    institution_id: int | None = None
    user_id: int | None = None


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(min_length=10)


class Student(BaseModel):
    id: str
    first_name: str
    last_name: str
    class_name: str
    school_name: str


class Lesson(BaseModel):
    start_time: str
    end_time: str
    subject: str
    teacher: str | None = None
    room: str | None = None
    change_type: LessonChangeType | None = None
    note: str | None = None


class ScheduleDay(BaseModel):
    date: DateType
    lessons: list[Lesson]


class HomeworkItem(BaseModel):
    id: str
    subject: str
    text: str
    due_date: DateType
    done: bool = False


class HomeworkDoneRequest(BaseModel):
    done: bool


class ExamItem(BaseModel):
    id: str
    subject: str
    topic: str
    date: DateType


class GradeItem(BaseModel):
    subject: str
    grade: str
    weight: float | None = None
    date: DateType | None = None
    comment: str | None = None


class SubjectStats(BaseModel):
    subject: str
    average: float
    grade_count: int
    trend: str  # "improving" | "stable" | "declining"
    grade_values: list[float] = Field(default_factory=list)


class GradeStats(BaseModel):
    subjects: list[SubjectStats]
    overall_gpa: float | None = None
    best_subject: str | None = None
    worst_subject: str | None = None


class EventItem(BaseModel):
    id: str
    title: str
    start: datetime
    end: datetime
    location: str | None = None
    description: str | None = None


class AbsenceItem(BaseModel):
    id: str
    date: DateType
    periods: list[str] = Field(default_factory=list)
    reason: str | None = None
    excused: bool = False


class MessageItem(BaseModel):
    id: str
    sender: str
    subject: str
    body_preview: str
    date: datetime
    read: bool = False


class LoginContext(BaseModel):
    account_id: str
    email: str
    school_id: str | None = None
    institution_id: int | None = None
    user_id: int | None = None
    students: list[Student]


class SessionInfo(BaseModel):
    account_id: str
    email: str
    role: Role
    school_id: str | None = None
    student_ids: list[str]
    created_at: datetime
    expires_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_expires_in: int
    session: SessionInfo


class WebhookEventType(str, Enum):
    HOMEWORK_NEW = "homework.new"
    GRADE_NEW = "grade.new"
    SCHEDULE_CHANGE = "schedule.change"
    ABSENCE_NEW = "absences.new"
    MESSAGE_NEW = "message.new"
    SYNC_COMPLETED = "sync.completed"
    TEST = "test"


class WebhookCreateRequest(BaseModel):
    url: AnyHttpUrl
    event_types: list[WebhookEventType] = Field(default_factory=lambda: [WebhookEventType.HOMEWORK_NEW, WebhookEventType.GRADE_NEW])
    secret: str | None = None


class WebhookSubscriptionInfo(BaseModel):
    id: str
    url: AnyHttpUrl
    event_types: list[WebhookEventType]
    active: bool
    created_at: datetime
    last_delivery_at: datetime | None = None
    last_error: str | None = None


class SyncRefreshRequest(BaseModel):
    schedule: bool = True
    homework: bool = True
    exams: bool = True
    grades: bool = True
    events: bool = True
    absences: bool = True
    messages: bool = True
    force_refresh: bool = True


class SyncRefreshResult(BaseModel):
    students_processed: int
    schedule_days: int
    homework_items: int
    exams: int
    grades: int
    events: int
    absences: int
    messages: int
    triggered_events: int


class CacheStats(BaseModel):
    backend: str
    key_count: int
    hit_count: int
    miss_count: int
    hit_rate: float
