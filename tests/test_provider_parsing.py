"""Parsing tests for the real Schulmanager response shapes (captured 2026-07-18).

_api_call is monkeypatched to return canned payloads keyed by (module, endpoint), so these
exercise the provider's parsing without any network.
"""
from __future__ import annotations

import asyncio

from schulmanager_api.models.schemas import LoginContext, Student
from schulmanager_api.providers.selenium import SeleniumAccountSession, SeleniumSchulmanagerProvider

STUDENT_ID = "111"


def _provider_with_canned(responses: dict[tuple[str, str], object]) -> tuple[SeleniumSchulmanagerProvider, LoginContext]:
    provider = SeleniumSchulmanagerProvider()
    student_raw = {"id": STUDENT_ID, "firstname": "Max", "lastname": "Muster", "classId": 468529, "className": "10a"}
    session = SeleniumAccountSession(
        account_id="acc_test", token="t", bundle_version="b", institution_id=1, user_id=1,
        school_name="Schule", students_by_id={STUDENT_ID: student_raw},
    )
    provider._sessions["acc_test"] = session

    async def fake_api_call(sess, module, endpoint, parameters, *, soft=False):
        return responses.get((module, endpoint), [])

    provider._api_call = fake_api_call  # type: ignore[assignment]

    context = LoginContext(
        account_id="acc_test", email="a@b.de",
        students=[Student(id=STUDENT_ID, first_name="Max", last_name="Muster", class_name="10a", school_name="Schule")],
    )
    return provider, context


def test_get_absences_from_history_list() -> None:
    responses = {
        ("classbook", "get-current-next-or-previous-term"): {"start": "2025-09-16", "end": "2026-07-31", "id": 28138, "preventAsCurrentTerm": False},
        ("classbook", "get-history-absences-list"): [
            {"date": "2026-07-13", "from": "2026-07-13T08:00:00", "until": "2026-07-13T09:30:00",
             "excused": {"id": 1}, "comment": "Arzttermin", "sickNote": None, "exemptionRequest": None, "id": 501},
            {"date": "2026-07-17", "from": None, "until": None,
             "excused": None, "comment": None, "sickNote": None, "exemptionRequest": None, "id": 502},
        ],
    }
    provider, ctx = _provider_with_canned(responses)
    absences = asyncio.run(provider.get_absences(ctx, STUDENT_ID))
    assert len(absences) == 2
    # Newest first
    assert absences[0].date.isoformat() == "2026-07-17"
    excused = next(a for a in absences if a.id == "501")
    assert excused.excused is True
    assert excused.reason == "Arzttermin"
    assert excused.periods == ["08:00–09:30"]
    unexcused = next(a for a in absences if a.id == "502")
    assert unexcused.excused is False


def test_get_events_from_calendar() -> None:
    responses = {
        ("calendar", "get-events-for-user"): {
            "nonRecurringEvents": [
                {"summary": "Elternabend", "start": "2026-07-20T18:00:00", "end": "2026-07-20T19:30:00",
                 "location": "Aula", "description": "Infos", "id": 7, "allDay": False},
            ],
            "recurringEvents": [],
        },
    }
    provider, ctx = _provider_with_canned(responses)
    events = asyncio.run(provider.get_events(ctx, STUDENT_ID))
    assert len(events) == 1
    assert events[0].title == "Elternabend"
    assert events[0].location == "Aula"


def test_get_homework_stable_hash_id() -> None:
    responses = {
        ("classbook", "get-homework"): [
            {"date": "2026-07-15", "subject": "Mathe", "homework": "Seite 42"},
        ],
    }
    provider, ctx = _provider_with_canned(responses)
    hw1 = asyncio.run(provider.get_homework(ctx, STUDENT_ID, open_only=False))
    hw2 = asyncio.run(provider.get_homework(ctx, STUDENT_ID, open_only=False))
    assert hw1[0].id.startswith("hw_")
    # Deterministic across calls (content hash)
    assert hw1[0].id == hw2[0].id
    assert hw1[0].subject == "Mathe"


def test_get_grades_includes_individual_grades() -> None:
    payload = {
        "courses": [{"id": 10, "subjectId": 394484, "subject": {"name": "Mathe", "abbreviation": "M"}}],
        "gradingEvents": [
            {"courseId": 10, "gradeTypeId": 1, "date": "2026-05-01", "topic": "KA1", "weighting": 2,
             "grades": [{"value": "2", "weighting": 2}]},
        ],
        "typePresets": [],
        "indiviualGrades": [
            {"courseId": 10, "value": "1", "weighting": 1, "topic": "Mündlich", "date": "2026-06-01"},
        ],
    }
    responses = {("grades", "get-grading-information-for-student"): payload}
    provider, ctx = _provider_with_canned(responses)
    grades = asyncio.run(provider.get_grades(ctx, STUDENT_ID))
    values = sorted(g.grade for g in grades)
    assert values == ["1", "2"]  # event grade + individual grade
    assert all(g.subject == "Mathe" for g in grades)


def test_get_payments_from_invoicing() -> None:
    responses = {
        ("invoicing", "poqa"): [
            {
                "id": 900, "number": 42, "date": "2026-07-01", "dueDate": "2026-07-20",
                "items": [{"name": "Klassenfahrt"}],
                "studentInvoices": [{"sum": "120.00", "paidSum": "0.00", "paid": False}],
            },
            {
                "id": 901, "number": 21, "date": "2026-05-01", "dueDate": "2026-05-15",
                "items": [{"name": "Kopiergeld"}],
                "studentInvoices": [{"sum": "15.00", "paidSum": "15.00", "paid": True}],
            },
        ],
    }
    provider, ctx = _provider_with_canned(responses)
    payments = asyncio.run(provider.get_payments(ctx, STUDENT_ID))
    assert len(payments) == 2
    # Unpaid first
    assert payments[0].paid is False
    unpaid = next(p for p in payments if p.id == "900")
    assert unpaid.title == "Klassenfahrt"
    assert unpaid.amount == 120.0
    assert unpaid.invoice_number == "42"


def test_get_learning_units() -> None:
    responses = {
        ("learning", "get-learning-courses"): [
            {"id": 10, "subjectId": 1, "subject": {"name": "Digitale Bildung", "abbreviation": "DB"}},
        ],
        ("learning", "get-course-units"): [
            {"id": "u1", "name": "Arbeitsblatt 1", "publicationTimestamp": "2026-07-10T09:00:00",
             "studentStatuses": [{"id": "s1", "seen": True, "done": False}]},
        ],
    }
    provider, ctx = _provider_with_canned(responses)
    units = asyncio.run(provider.get_learning(ctx, STUDENT_ID))
    assert len(units) == 1
    assert units[0].subject == "Digitale Bildung"
    assert units[0].title == "Arbeitsblatt 1"
    assert units[0].seen is True and units[0].done is False


def test_get_messages_unread_count() -> None:
    responses = {
        ("messenger", "get-subscriptions"): [
            {"id": "sub1", "unreadCount": 3, "threadId": "t1",
             "thread": {"subject": "Betreff", "senderString": "Frau A", "lastMessageTimestamp": "2026-07-12T10:00:00"}},
        ],
    }
    provider, ctx = _provider_with_canned(responses)
    messages = asyncio.run(provider.get_messages(ctx, STUDENT_ID))
    assert len(messages) == 1
    assert messages[0].unread_count == 3
    assert messages[0].read is False
    assert messages[0].subject == "Betreff"
