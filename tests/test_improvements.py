"""Tests for the reliability/feature improvements (letters, messenger, tz, weights, cache)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from schulmanager_api.main import app
from schulmanager_api.models.schemas import GradeItem
from schulmanager_api.services.grade_stats import compute_grade_stats
from schulmanager_api.services.ical import build_ics
from schulmanager_api.services.sqlite_cache import SQLiteTTLCache

client = TestClient(app)


def _token() -> str:
    r = client.post("/auth/login", json={"email": "demo@example.com", "password": "secret"})
    assert r.status_code == 200
    return r.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _sid(token: str) -> str:
    r = client.get("/students", headers=_auth(token))
    return r.json()[0]["id"]


# --------------------------------------------------------------------------- #
# Elternbriefe (letters)
# --------------------------------------------------------------------------- #

def test_letters_returns_list() -> None:
    token = _token()
    sid = _sid(token)
    r = client.get(f"/students/{sid}/letters", headers=_auth(token))
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list) and data
    item = data[0]
    assert {"id", "title", "read", "requires_confirmation", "attachment_count"} <= set(item)


def test_letters_requires_auth() -> None:
    assert client.get("/students/stu_001/letters").status_code == 401


# --------------------------------------------------------------------------- #
# Messenger: inbox unread_count + thread detail
# --------------------------------------------------------------------------- #

def test_messages_have_unread_count() -> None:
    token = _token()
    sid = _sid(token)
    r = client.get(f"/students/{sid}/messages", headers=_auth(token))
    assert r.status_code == 200
    data = r.json()
    assert data and "unread_count" in data[0]


def test_message_thread_returns_messages() -> None:
    token = _token()
    sid = _sid(token)
    r = client.get(f"/students/{sid}/messages/msg_001", headers=_auth(token))
    assert r.status_code == 200
    body = r.json()
    assert body["subscription_id"] == "msg_001"
    assert isinstance(body["messages"], list) and body["messages"]
    assert {"id", "sender", "text", "date", "has_attachments"} <= set(body["messages"][0])


# --------------------------------------------------------------------------- #
# Homework local done-override persists across reads and both views
# --------------------------------------------------------------------------- #

def test_homework_override_persists_and_syncs_views() -> None:
    token = _token()
    sid = _sid(token)

    full = client.get(f"/students/{sid}/homework", headers=_auth(token)).json()
    open_item = next(hw for hw in full if not hw["done"])
    hw_id = open_item["id"]

    # Mark it done.
    patch = client.patch(f"/students/{sid}/homework/{hw_id}", json={"done": True}, headers=_auth(token))
    assert patch.status_code == 200 and patch.json()["done"] is True

    # A fresh full read reflects done=True (override applied even after list-cache invalidation).
    again = client.get(f"/students/{sid}/homework", headers=_auth(token)).json()
    assert next(hw for hw in again if hw["id"] == hw_id)["done"] is True

    # And it no longer shows in the open-only view.
    open_only = client.get(f"/students/{sid}/homework?open_only=true", headers=_auth(token)).json()
    assert all(hw["id"] != hw_id for hw in open_only)


# --------------------------------------------------------------------------- #
# Weighted grade statistics
# --------------------------------------------------------------------------- #

def test_grade_stats_weighting_within_subject() -> None:
    grades = [
        GradeItem(subject="Mathe", grade="1", weight=1.0, date=date(2026, 1, 1)),
        GradeItem(subject="Mathe", grade="3", weight=3.0, date=date(2026, 2, 1)),
    ]
    stats = compute_grade_stats(grades)
    # (1*1 + 3*3) / (1+3) = 2.5  (unweighted would be 2.0)
    assert stats.subjects[0].average == pytest.approx(2.5)


def test_overall_gpa_weighted_across_subjects() -> None:
    grades = [
        GradeItem(subject="A", grade="1", weight=1.0),
        GradeItem(subject="B", grade="3", weight=1.0),
        GradeItem(subject="B", grade="3", weight=1.0),
    ]
    stats = compute_grade_stats(grades)
    # weighted by grade weight: (1*1 + 3*2)/3 = 2.33 (mean-of-means would be 2.0)
    assert stats.overall_gpa == pytest.approx(2.33, abs=0.01)


# --------------------------------------------------------------------------- #
# ICS timezone: local school time -> correct UTC instant across DST
# --------------------------------------------------------------------------- #

def test_ics_lesson_uses_school_local_time() -> None:
    tomorrow = date.today() + timedelta(days=1)
    schedule = [{
        "date": tomorrow.isoformat(),
        "lessons": [{"start_time": "08:00", "end_time": "08:45", "subject": "Mathe", "teacher": "", "room": ""}],
    }]
    content = build_ics("Test", schedule, [], [], tz_name="Europe/Berlin").decode("utf-8")

    expected = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 8, 0, tzinfo=ZoneInfo("Europe/Berlin"))
    expected_utc = expected.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    assert f"DTSTART:{expected_utc}" in content
    # And it must NOT be the naive-as-UTC bug value (08:00Z).
    assert f"DTSTART:{tomorrow.strftime('%Y%m%d')}T080000Z" not in content


# --------------------------------------------------------------------------- #
# SQLite cache: delete_prefix must not treat '_' as a wildcard
# --------------------------------------------------------------------------- #

def test_sqlite_delete_prefix_escapes_wildcards(tmp_path) -> None:
    cache = SQLiteTTLCache(str(tmp_path / "c.sqlite3"))
    cache.set("acc_a:1:x", "keep-me", 60)   # '_' here must stay literal
    cache.set("accXa:1:x", "other", 60)
    cache.delete_prefix("acc_a:")
    assert cache.get("acc_a:1:x") is None
    assert cache.get("accXa:1:x") == "other"  # underscore must not have matched 'X'


# --------------------------------------------------------------------------- #
# Sync now includes letters
# --------------------------------------------------------------------------- #

def test_sync_includes_letters() -> None:
    token = _token()
    r = client.post("/sync/refresh", json={}, headers=_auth(token))
    assert r.status_code == 200
    body = r.json()
    assert "letters" in body
    assert body["letters"] >= 1


# --------------------------------------------------------------------------- #
# _api_call error surfacing (the core "features silently return []" fix)
# --------------------------------------------------------------------------- #

class _FakeResp:
    def __init__(self, status_code: int, payload) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, resp: _FakeResp) -> None:
        self._resp = resp

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, *args, **kwargs):
        return self._resp


def _fake_session():
    from schulmanager_api.providers.selenium import SeleniumAccountSession

    return SeleniumAccountSession(
        account_id="acc", token="t", bundle_version="b",
        institution_id=1, user_id=1, school_name="S", students_by_id={},
    )


def test_api_call_error_surfacing(monkeypatch) -> None:
    import asyncio

    from fastapi import HTTPException

    from schulmanager_api.providers import selenium as sel

    provider = sel.SeleniumSchulmanagerProvider()
    session = _fake_session()

    def use(payload, status=200):
        resp = _FakeResp(status, payload)
        monkeypatch.setattr(sel.httpx, "AsyncClient", lambda *a, **k: _FakeClient(resp))

    # Inner status 200 -> returns data
    use({"results": [{"status": 200, "data": [1, 2, 3]}]})
    assert asyncio.run(provider._api_call(session, "m", "e", {})) == [1, 2, 3]

    # Inner error, hard mode -> raises 502 (no more silent [])
    use({"results": [{"status": 500, "error": "boom"}]})
    with pytest.raises(HTTPException) as ei:
        asyncio.run(provider._api_call(session, "m", "e", {}))
    assert ei.value.status_code == 502

    # Inner error, soft mode -> [] (optional module may be disabled)
    use({"results": [{"status": 500, "error": "boom"}]})
    assert asyncio.run(provider._api_call(session, "m", "e", {}, soft=True)) == []

    # Inner 401 -> re-auth (401) even in soft mode
    use({"results": [{"status": 401}]})
    with pytest.raises(HTTPException) as ei2:
        asyncio.run(provider._api_call(session, "m", "e", {}, soft=True))
    assert ei2.value.status_code == 401

    # Outer HTTP 401 -> re-auth
    use({}, status=401)
    with pytest.raises(HTTPException) as ei3:
        asyncio.run(provider._api_call(session, "m", "e", {}))
    assert ei3.value.status_code == 401
