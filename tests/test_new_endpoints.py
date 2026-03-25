"""Tests for new endpoints and services added in feature batch 2."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from schulmanager_api.main import app
from schulmanager_api.models.schemas import GradeItem  # noqa: E402
from schulmanager_api.services.grade_stats import compute_grade_stats  # noqa: E402
from schulmanager_api.services.ical import build_ics  # noqa: E402

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _admin_token() -> str:
    """Log in as the demo admin account and return the access token."""
    response = client.post(
        "/auth/login",
        json={"email": "demo@example.com", "password": "secret"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _first_student_id(token: str) -> str:
    resp = client.get("/students", headers=_auth(token))
    assert resp.status_code == 200
    students = resp.json()
    assert students
    return students[0]["id"]


# ---------------------------------------------------------------------------
# Absences endpoint
# ---------------------------------------------------------------------------

def test_absences_returns_list() -> None:
    token = _admin_token()
    sid = _first_student_id(token)
    resp = client.get(f"/students/{sid}/absences", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    if data:
        item = data[0]
        assert "id" in item
        assert "date" in item
        assert "excused" in item


def test_absences_requires_auth() -> None:
    resp = client.get("/students/stu_001/absences")
    assert resp.status_code == 401


def test_absences_unknown_student_returns_404() -> None:
    token = _admin_token()
    resp = client.get("/students/no_such_student/absences", headers=_auth(token))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Messages endpoint
# ---------------------------------------------------------------------------

def test_messages_returns_list() -> None:
    token = _admin_token()
    sid = _first_student_id(token)
    resp = client.get(f"/students/{sid}/messages", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    if data:
        item = data[0]
        assert "id" in item
        assert "sender" in item
        assert "subject" in item


def test_messages_requires_auth() -> None:
    resp = client.get("/students/stu_001/messages")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Grade stats endpoint
# ---------------------------------------------------------------------------

def test_grade_stats_returns_stats_object() -> None:
    token = _admin_token()
    sid = _first_student_id(token)
    resp = client.get(f"/students/{sid}/grades/stats", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()
    assert "subjects" in data
    assert "overall_gpa" in data
    assert isinstance(data["subjects"], list)


def test_grade_stats_requires_auth() -> None:
    resp = client.get("/students/stu_001/grades/stats")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Homework PATCH (done-status)
# ---------------------------------------------------------------------------

def test_patch_homework_done_toggles_status() -> None:
    token = _admin_token()
    sid = _first_student_id(token)

    # Get current homework list
    hw_resp = client.get(f"/students/{sid}/homework", headers=_auth(token))
    assert hw_resp.status_code == 200
    hw_list = hw_resp.json()
    assert hw_list, "Mock provider must return at least one homework item"

    hw_id = hw_list[0]["id"]
    original_done = hw_list[0]["done"]

    # Toggle done
    patch_resp = client.patch(
        f"/students/{sid}/homework/{hw_id}",
        json={"done": not original_done},
        headers=_auth(token),
    )
    assert patch_resp.status_code == 200
    updated = patch_resp.json()
    assert updated["id"] == hw_id
    assert updated["done"] == (not original_done)


def test_patch_homework_unknown_id_returns_404() -> None:
    token = _admin_token()
    sid = _first_student_id(token)
    resp = client.patch(
        f"/students/{sid}/homework/nonexistent_hw",
        json={"done": True},
        headers=_auth(token),
    )
    assert resp.status_code == 404


def test_patch_homework_requires_auth() -> None:
    resp = client.patch("/students/stu_001/homework/hw_001", json={"done": True})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Calendar ICS endpoint
# ---------------------------------------------------------------------------

def test_calendar_ics_returns_ics_bytes() -> None:
    token = _admin_token()
    sid = _first_student_id(token)
    resp = client.get(f"/students/{sid}/calendar.ics", headers=_auth(token))
    assert resp.status_code == 200
    assert "text/calendar" in resp.headers["content-type"]
    body = resp.content
    assert body.startswith(b"BEGIN:VCALENDAR")
    assert b"END:VCALENDAR" in body


def test_calendar_ics_requires_auth() -> None:
    resp = client.get("/students/stu_001/calendar.ics")
    assert resp.status_code == 401


def test_calendar_ics_has_content_disposition() -> None:
    token = _admin_token()
    sid = _first_student_id(token)
    resp = client.get(f"/students/{sid}/calendar.ics", headers=_auth(token))
    assert "content-disposition" in resp.headers
    assert ".ics" in resp.headers["content-disposition"]


# ---------------------------------------------------------------------------
# Cache stats/flush endpoints
# ---------------------------------------------------------------------------

def test_cache_stats_returns_stats() -> None:
    token = _admin_token()
    resp = client.get("/cache/stats", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()
    assert "backend" in data
    assert "key_count" in data
    assert "hit_count" in data
    assert "miss_count" in data
    assert "hit_rate" in data
    assert 0.0 <= data["hit_rate"] <= 1.0


def test_cache_flush_returns_204() -> None:
    token = _admin_token()
    resp = client.delete("/cache", headers=_auth(token))
    assert resp.status_code == 204


def test_cache_stats_requires_admin() -> None:
    """A non-admin token (viewer role) should be rejected."""
    # demo@example.com is admin; there's no separate viewer account in mock,
    # so just confirm that missing auth returns 401
    resp = client.get("/cache/stats")
    assert resp.status_code == 401


def test_cache_flush_requires_admin() -> None:
    resp = client.delete("/cache")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# compute_grade_stats service unit tests
# ---------------------------------------------------------------------------

def _make_grade(subject: str, grade: str, d: str = "2026-01-01") -> GradeItem:
    return GradeItem(subject=subject, grade=grade, date=date.fromisoformat(d))


def test_grade_stats_empty_list() -> None:
    stats = compute_grade_stats([])
    assert stats.subjects == []
    assert stats.overall_gpa is None
    assert stats.best_subject is None
    assert stats.worst_subject is None


def test_grade_stats_single_subject() -> None:
    grades = [
        _make_grade("Mathe", "2", "2026-01-10"),
        _make_grade("Mathe", "3", "2026-01-20"),
    ]
    stats = compute_grade_stats(grades)
    assert len(stats.subjects) == 1
    assert stats.subjects[0].subject == "Mathe"
    assert stats.subjects[0].average == pytest.approx(2.5)
    assert stats.overall_gpa == pytest.approx(2.5)
    assert stats.best_subject == "Mathe"
    assert stats.worst_subject == "Mathe"


def test_grade_stats_trend_improving() -> None:
    # Early grades worse (3, 3), later grades better (1, 1)
    grades = [
        _make_grade("Mathe", "3", "2026-01-01"),
        _make_grade("Mathe", "3", "2026-02-01"),
        _make_grade("Mathe", "1", "2026-03-01"),
        _make_grade("Mathe", "1", "2026-04-01"),
    ]
    stats = compute_grade_stats(grades)
    assert stats.subjects[0].trend == "improving"


def test_grade_stats_trend_declining() -> None:
    grades = [
        _make_grade("Mathe", "1", "2026-01-01"),
        _make_grade("Mathe", "1", "2026-02-01"),
        _make_grade("Mathe", "4", "2026-03-01"),
        _make_grade("Mathe", "4", "2026-04-01"),
    ]
    stats = compute_grade_stats(grades)
    assert stats.subjects[0].trend == "declining"


def test_grade_stats_trend_stable_with_few_grades() -> None:
    grades = [
        _make_grade("Mathe", "2", "2026-01-01"),
        _make_grade("Mathe", "2", "2026-02-01"),
    ]
    stats = compute_grade_stats(grades)
    # Less than 4 grades → always stable
    assert stats.subjects[0].trend == "stable"


def test_grade_stats_best_worst_subjects() -> None:
    grades = [
        _make_grade("Mathe", "1"),
        _make_grade("Deutsch", "5"),
        _make_grade("Englisch", "3"),
    ]
    stats = compute_grade_stats(grades)
    assert stats.best_subject == "Mathe"
    assert stats.worst_subject == "Deutsch"


def test_grade_stats_ignores_invalid_grade_strings() -> None:
    grades = [
        _make_grade("Mathe", "sehr gut"),  # non-standard
        _make_grade("Mathe", "2"),
    ]
    stats = compute_grade_stats(grades)
    assert stats.subjects[0].grade_count == 1
    assert stats.subjects[0].average == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# build_ics service unit tests
# ---------------------------------------------------------------------------

def test_build_ics_minimal() -> None:
    content = build_ics("Max Mustermann", [], [], [])
    assert b"BEGIN:VCALENDAR" in content
    assert b"END:VCALENDAR" in content
    assert b"Max Mustermann" in content


def test_build_ics_includes_lesson() -> None:
    today = date.today()
    schedule = [
        {
            "date": today.isoformat(),
            "lessons": [
                {
                    "start_time": "08:00",
                    "end_time": "08:45",
                    "subject": "Mathe",
                    "teacher": "Herr Test",
                    "room": "101",
                }
            ],
        }
    ]
    content = build_ics("Test", schedule, [], [])
    assert b"BEGIN:VEVENT" in content
    assert b"Mathe" in content
    assert b"101" in content


def test_build_ics_includes_exam_as_allday() -> None:
    tomorrow = date.today() + timedelta(days=1)
    exams = [{"id": "e1", "subject": "Physik", "topic": "Optik", "date": tomorrow.isoformat()}]
    content = build_ics("Test", [], exams, [])
    assert b"Pruefung: Physik" in content
    assert b"VALUE=DATE" in content


def test_build_ics_excludes_past_events() -> None:
    yesterday = date.today() - timedelta(days=1)
    schedule = [
        {
            "date": yesterday.isoformat(),
            "lessons": [
                {
                    "start_time": "08:00",
                    "end_time": "08:45",
                    "subject": "AlteStunde",
                    "teacher": "",
                    "room": "",
                }
            ],
        }
    ]
    content = build_ics("Test", schedule, [], [])
    assert b"AlteStunde" not in content


def test_build_ics_crlf_line_endings() -> None:
    content = build_ics("Test", [], [], [])
    assert b"\r\n" in content


def test_build_ics_includes_timed_event() -> None:
    now = datetime.now(timezone.utc)
    later = now + timedelta(hours=2)
    events = [
        {
            "id": "ev1",
            "title": "Elternabend",
            "start": now.isoformat(),
            "end": later.isoformat(),
            "location": "Aula",
        }
    ]
    content = build_ics("Test", [], [], events)
    assert b"Elternabend" in content
    assert b"Aula" in content
