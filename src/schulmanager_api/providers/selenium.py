from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import logging
import re
import time
from threading import Lock
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from fastapi import HTTPException

from schulmanager_api.config import Settings, get_settings
from schulmanager_api.models.schemas import (
    AbsenceItem,
    AuthRequest,
    EventItem,
    ExamItem,
    GradeItem,
    HomeworkItem,
    Lesson,
    LessonChangeType,
    LetterItem,
    LoginContext,
    MessageItem,
    MessageThread,
    ScheduleDay,
    Student,
    ThreadMessage,
)

logger = logging.getLogger("schulmanager_api.provider")

LOGIN_API_URL = "https://login.schulmanager-online.de/api/login"
GET_SALT_URL = "https://login.schulmanager-online.de/api/get-salt"
CALLS_URL = "https://login.schulmanager-online.de/api/calls"
LOGIN_PAGE_URL = "https://login.schulmanager-online.de/#/login"
INDEX_URL = "https://login.schulmanager-online.de/"


def _school_tz() -> ZoneInfo | timezone:
    try:
        return ZoneInfo(get_settings().school_timezone)
    except (ZoneInfoNotFoundError, ValueError, Exception):  # noqa: BLE001 - fall back to UTC
        return timezone.utc


@dataclass(slots=True)
class SeleniumAccountSession:
    account_id: str
    token: str
    bundle_version: str
    institution_id: int | None
    user_id: int | None
    school_name: str
    students_by_id: dict[str, dict[str, Any]]
    grade_term_ids: list[int] | None = None
    subjects_by_id: dict[int, str] | None = None
    class_hours_by_key: dict[str, dict[str, Any]] | None = None
    grades_params: dict[str, Any] | None = None


class SeleniumSchulmanagerProvider:
    """Schulmanager provider: real HTTP login (get-salt + login) and api/calls data fetches.

    The optional Selenium/Chrome step only *double-checks* credentials in a real browser and is
    off by default (SM_SELENIUM_REQUIRE_BROWSER); the httpx api/login below is the actual auth.
    """

    # bundleVersion is deploy-global, not per-account. Cache it across logins with a TTL.
    _bundle_lock = Lock()
    _bundle_cache: tuple[str, float] | None = None

    def __init__(self) -> None:
        self._settings: Settings = get_settings()
        self._sessions: dict[str, SeleniumAccountSession] = {}
        self._lock = Lock()

    async def login(self, credentials: AuthRequest) -> LoginContext:
        # The browser step is a redundant credential double-check; only run it when explicitly
        # requested. The api/login call below is the real authentication.
        if self._settings.selenium_require_browser:
            try:
                await asyncio.to_thread(self._verify_login_with_browser, credentials)
            except HTTPException:
                raise
            except Exception as exc:  # noqa: BLE001 - surface infra failure as a clean 502
                raise HTTPException(
                    status_code=502,
                    detail=(
                        "Browser-Login-Pruefung fehlgeschlagen (Chrome/Chromedriver verfuegbar? "
                        f"{type(exc).__name__}). SM_SELENIUM_REQUIRE_BROWSER=false deaktiviert diesen Schritt."
                    ),
                ) from exc

        login_data = await self._api_login(credentials)

        token = str(login_data.get("jwt") or "")
        if not token:
            raise HTTPException(status_code=401, detail="Login fehlgeschlagen (kein JWT erhalten)")

        user = login_data.get("user") or {}
        institution_id = self._opt_int(user.get("institutionId")) or credentials.institution_id
        user_id = self._opt_int(user.get("id")) or credentials.user_id
        school_name = self._extract_school_name(user, credentials)

        students_by_id = self._extract_students(user, school_name)
        if not students_by_id:
            # Some accounts expose student data outside "user".
            students_by_id = self._extract_students(login_data, school_name)
        if not students_by_id:
            raise HTTPException(
                status_code=502,
                detail=(
                    "Keine Schueler im Schulmanager-Account gefunden. "
                    "Account ist evtl. Lehrer/ohne verknuepfte Kinder."
                ),
            )

        account_id = f"acc_{credentials.email.lower().replace('@', '_').replace('.', '_')}"
        bundle_version = await self._discover_bundle_version()

        session = SeleniumAccountSession(
            account_id=account_id,
            token=token,
            bundle_version=bundle_version,
            institution_id=institution_id,
            user_id=user_id,
            school_name=school_name,
            students_by_id=students_by_id,
        )
        with self._lock:
            self._sessions[account_id] = session

        students = [self._student_model(raw) for raw in students_by_id.values()]

        return LoginContext(
            account_id=account_id,
            email=credentials.email,
            school_id=credentials.school_id,
            institution_id=institution_id,
            user_id=user_id,
            students=students,
        )

    async def get_students(self, context: LoginContext) -> list[Student]:
        session = self._require_session(context)
        return [self._student_model(raw) for raw in session.students_by_id.values()]

    async def get_schedule(
        self,
        context: LoginContext,
        student_id: str,
        from_date: date | None,
        to_date: date | None,
    ) -> list[ScheduleDay]:
        session, student_raw = self._require_student_session(context, student_id)
        class_hours_by_key = await self._get_class_hours_by_key(session)

        start = from_date or date.today()
        end = to_date or (start + timedelta(days=6))

        parameters = {
            "student": self._student_payload(student_raw),
            "start": start.isoformat(),
            "end": end.isoformat(),
        }

        rows = await self._api_call(session, "schedules", "get-actual-lessons", parameters)
        grouped: dict[date, list[Lesson]] = {}
        seen_per_day: dict[date, set[tuple[str, ...]]] = {}

        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                lesson_date, lesson = self._parse_schedule_lesson(row, class_hours_by_key)
                if lesson_date is None or lesson is None:
                    continue
                if lesson_date < start or lesson_date > end:
                    continue
                dedupe_key = (
                    lesson.start_time,
                    lesson.end_time,
                    lesson.subject,
                    lesson.teacher or "",
                    lesson.room or "",
                    lesson.change_type.value if lesson.change_type else "",
                    lesson.note or "",
                )
                seen = seen_per_day.setdefault(lesson_date, set())
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                grouped.setdefault(lesson_date, []).append(lesson)

        for day in list(grouped):
            grouped[day] = self._merge_parallel_day_lessons(grouped[day])

        return [
            ScheduleDay(date=day, lessons=grouped[day])
            for day in sorted(grouped)
        ]

    async def get_homework(
        self,
        context: LoginContext,
        student_id: str,
        open_only: bool,
    ) -> list[HomeworkItem]:
        session, _ = self._require_student_session(context, student_id)

        data = await self._api_call(
            session,
            "classbook",
            "get-homework",
            {"student": {"id": int(student_id)}},
        )

        items: list[HomeworkItem] = []
        if isinstance(data, list):
            for row in data:
                if not isinstance(row, dict):
                    continue
                due_date = self._parse_date(row.get("date")) or self._parse_date(row.get("dueDate")) or date.today()
                subject = self._extract_subject_text(row)
                text = self._as_text(
                    row.get("homework")
                    or row.get("task")
                    or row.get("text")
                    or row.get("description")
                    or "Hausaufgabe"
                )
                done = bool(row.get("done") or row.get("isDone") or row.get("completed"))
                item_id = self._as_text(row.get("id") or row.get("uuid") or f"hw_{student_id}_{len(items)}")

                items.append(
                    HomeworkItem(
                        id=item_id,
                        subject=subject,
                        text=text,
                        due_date=due_date,
                        done=done,
                    )
                )

        if open_only:
            return [item for item in items if not item.done]
        return items

    async def get_exams(self, context: LoginContext, student_id: str) -> list[ExamItem]:
        session, student_raw = self._require_student_session(context, student_id)

        start = date.today() - timedelta(days=30)
        end = date.today() + timedelta(days=180)

        rows = await self._api_call(
            session,
            "exams",
            "get-exams",
            {
                "student": self._student_payload(student_raw),
                "start": start.isoformat(),
                "end": end.isoformat(),
            },
        )

        output: list[ExamItem] = []
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                exam_date = self._parse_date(row.get("date"))
                if exam_date is None:
                    start_dt = self._parse_datetime(row.get("start"))
                    exam_date = start_dt.date() if start_dt else None
                if exam_date is None:
                    continue

                subject = self._extract_subject_text(row)
                topic = self._as_text(row.get("topic") or row.get("comment") or row.get("subjectText") or subject)
                item_id = self._as_text(row.get("id") or f"exam_{student_id}_{len(output)}")

                output.append(
                    ExamItem(
                        id=item_id,
                        subject=subject,
                        topic=topic,
                        date=exam_date,
                    )
                )

        return output

    async def get_grades(self, context: LoginContext, student_id: str) -> list[GradeItem]:
        session, _ = self._require_student_session(context, student_id)
        sid = int(student_id)

        today = date.today()
        if today.month >= 8:
            start = date(today.year, 8, 1)
            end = date(today.year + 1, 7, 31)
        else:
            start = date(today.year - 1, 8, 1)
            end = date(today.year, 7, 31)
        wide_start = today - timedelta(days=370)
        wide_end = today + timedelta(days=370)

        discovered_term_ids = await self._get_grade_term_ids(session, today)
        terms: list[int | None] = list(discovered_term_ids[:2])
        if self._settings.selenium_term_id not in terms:
            terms.append(self._settings.selenium_term_id)
        terms.append(None)
        primary_term = terms[0]

        parameter_candidates: list[dict[str, Any]] = []
        seen_params: set[str] = set()

        def add_params(
            range_start: date,
            range_end: date,
            term_id: int | None,
            grading_period_type: str | None,
        ) -> None:
            params: dict[str, Any] = {
                "studentId": sid,
                "start": range_start.isoformat(),
                "end": range_end.isoformat(),
            }
            if term_id is not None:
                params["termId"] = term_id
            if grading_period_type is not None:
                params["gradingPeriodType"] = grading_period_type

            marker = json.dumps(params, sort_keys=True)
            if marker in seen_params:
                return
            seen_params.add(marker)
            parameter_candidates.append(params)

        # 1) The shape that worked last time on this session (usually the only request needed).
        cached = session.grades_params
        if isinstance(cached, dict):
            add_params(start, end, cached.get("termId"), cached.get("gradingPeriodType"))

        # 2) A small, targeted probe set instead of the former ~24-combo cartesian brute force.
        for term in terms:
            add_params(start, end, term, "entireYear")
        add_params(start, end, primary_term, None)
        add_params(wide_start, wide_end, primary_term, "entireYear")

        # Hard cap to bound worst-case latency (each candidate is one sequential HTTP round-trip).
        parameter_candidates = parameter_candidates[:6]

        fallback_payload: dict[str, Any] | None = None
        subject_map = await self._get_subject_map(session)
        for params in parameter_candidates:
            rows = await self._api_call(
                session,
                "grades",
                "get-grading-information-for-student",
                params,
                soft=True,
            )
            payload = self._coerce_grades_payload(rows)
            if payload is None:
                continue

            payload_for_parse = dict(payload)
            payload_for_parse["_subject_map"] = subject_map
            parsed_items = self._parse_grade_items(payload_for_parse)
            if parsed_items:
                session.grades_params = {
                    "termId": params.get("termId"),
                    "gradingPeriodType": params.get("gradingPeriodType"),
                }
                return parsed_items

            if fallback_payload is None:
                fallback_payload = payload_for_parse

        if fallback_payload is not None:
            return self._parse_grade_items(fallback_payload)
        return []

    async def get_events(self, context: LoginContext, student_id: str) -> list[EventItem]:
        session, _ = self._require_student_session(context, student_id)

        start = date.today() - timedelta(days=30)
        end = date.today() + timedelta(days=180)

        data = await self._api_call(
            session,
            "exams",
            "poqa",
            {
                "action": {
                    "model": "modules/calendar/event",
                    "action": "findAll",
                    "parameters": [
                        {
                            "where": {
                                "start": {"$lte": f"{(end + timedelta(days=1)).isoformat()}T00:00:00.000Z"},
                                "end": {"$gte": f"{(start - timedelta(days=1)).isoformat()}T00:00:00.000Z"},
                            },
                            "include": [
                                {
                                    "association": "visibleForGroups",
                                    "required": True,
                                    "attributes": ["id"],
                                    "include": [
                                        {
                                            "association": "students",
                                            "required": True,
                                            "attributes": ["id"],
                                            "where": {"id": int(student_id)},
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                },
                "uiState": "main.modules.exams.view",
            },
        )

        events: list[EventItem] = []
        if isinstance(data, list):
            for row in data:
                if not isinstance(row, dict):
                    continue
                start_dt = self._parse_datetime(row.get("start"))
                end_dt = self._parse_datetime(row.get("end"))
                if start_dt is None or end_dt is None:
                    continue
                events.append(
                    EventItem(
                        id=self._as_text(row.get("id") or f"event_{student_id}_{len(events)}"),
                        title=self._as_text(row.get("summary") or row.get("title") or "Schultermin"),
                        start=start_dt,
                        end=end_dt,
                        location=self._opt_text(row.get("location")),
                        description=self._opt_text(row.get("description")),
                    )
                )

        return events

    async def get_absences(self, context: LoginContext, student_id: str) -> list[AbsenceItem]:
        session, student_raw = self._require_student_session(context, student_id)

        start = date.today() - timedelta(days=180)
        end = date.today() + timedelta(days=30)

        # NOTE: 'classbook/get-student-absences' is unconfirmed against public clients; if a live
        # traffic capture reveals the real Fehlzeiten endpoint, wire it in here. soft=True so a
        # wrong/disabled endpoint degrades to [] instead of failing the request (401 still raises).
        data = await self._api_call(
            session,
            "classbook",
            "get-student-absences",
            {
                "student": self._student_payload(student_raw),
                "start": start.isoformat(),
                "end": end.isoformat(),
            },
            soft=True,
        )

        absences: list[AbsenceItem] = []
        if isinstance(data, list):
            for row in data:
                if not isinstance(row, dict):
                    continue
                absence_date = self._parse_date(row.get("date") or row.get("absenceDate"))
                if absence_date is None:
                    continue

                periods_raw = row.get("lessons") or row.get("periods") or row.get("units") or []
                if isinstance(periods_raw, list):
                    periods = [str(p) for p in periods_raw if p is not None]
                else:
                    periods = []

                reason = self._opt_text(row.get("reason") or row.get("note") or row.get("comment"))
                excused = bool(row.get("excused") or row.get("isExcused") or row.get("justified"))
                item_id = self._as_text(row.get("id") or f"abs_{student_id}_{len(absences)}")

                absences.append(
                    AbsenceItem(
                        id=item_id,
                        date=absence_date,
                        periods=periods,
                        reason=reason,
                        excused=excused,
                    )
                )

        return absences

    async def get_messages(self, context: LoginContext, student_id: str) -> list[MessageItem]:
        """Messenger inbox: list of chat threads via messenger/get-subscriptions.

        (The old code used a non-existent 'messages'/'get-inbox' endpoint, which always failed.)
        """
        session, _ = self._require_student_session(context, student_id)

        data = await self._api_call(session, "messenger", "get-subscriptions", {}, soft=True)

        rows: list[Any]
        if isinstance(data, list):
            rows = data
        elif isinstance(data, dict):
            rows = data.get("subscriptions") or data.get("data") or []
        else:
            rows = []

        messages: list[MessageItem] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            thread = row.get("thread") if isinstance(row.get("thread"), dict) else row

            subscription_id = self._as_text(row.get("id") or thread.get("id") or f"sub_{len(messages)}")
            subject = self._as_text(thread.get("subject") or thread.get("title") or "(kein Betreff)")
            sender = self._as_text(
                thread.get("senderString")
                or thread.get("sender")
                or thread.get("recipientString")
                or "Unbekannt"
            ) or "Unbekannt"

            msg_dt = self._parse_datetime(
                thread.get("lastMessageTimestamp")
                or thread.get("updatedAt")
                or thread.get("createdAt")
                or row.get("lastMessageTimestamp")
            ) or datetime.now(timezone.utc)

            unread = self._opt_int(row.get("unreadCount") or thread.get("unreadCount")) or 0
            preview = self._opt_text(thread.get("lastMessagePreview") or thread.get("preview")) or ""
            if preview and len(preview) > 200:
                preview = preview[:197] + "..."

            messages.append(
                MessageItem(
                    id=subscription_id,
                    sender=sender,
                    subject=subject,
                    body_preview=preview,
                    date=msg_dt,
                    read=unread == 0,
                    unread_count=unread,
                )
            )

        messages.sort(key=lambda m: m.date, reverse=True)
        return messages

    async def get_message_thread(
        self, context: LoginContext, student_id: str, subscription_id: str
    ) -> MessageThread:
        """All messages inside one chat thread (messenger/get-messages-by-subscription)."""
        session, _ = self._require_student_session(context, student_id)

        data = await self._api_call(
            session,
            "messenger",
            "get-messages-by-subscription",
            {"subscriptionId": self._opt_int(subscription_id) or subscription_id},
            soft=True,
        )

        rows: list[Any]
        subject = ""
        if isinstance(data, dict):
            rows = data.get("messages") or data.get("data") or []
            subject = self._as_text(data.get("subject") or (data.get("thread") or {}).get("subject") or "")
        elif isinstance(data, list):
            rows = data
        else:
            rows = []

        thread_messages: list[ThreadMessage] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            sender_raw = row.get("sender") or row.get("author") or {}
            if isinstance(sender_raw, dict):
                first = self._as_text(sender_raw.get("firstname") or sender_raw.get("firstName"))
                last = self._as_text(sender_raw.get("lastname") or sender_raw.get("lastName"))
                sender = f"{first} {last}".strip() or "Unbekannt"
            else:
                sender = self._as_text(sender_raw) or "Unbekannt"

            text = self._as_text(row.get("text") or row.get("body") or row.get("content") or "")
            attachments = row.get("attachments")
            has_attach = bool(isinstance(attachments, list) and attachments)
            msg_dt = self._parse_datetime(
                row.get("createdAt") or row.get("sentAt") or row.get("date")
            ) or datetime.now(timezone.utc)

            thread_messages.append(
                ThreadMessage(
                    id=self._as_text(row.get("id") or f"tmsg_{len(thread_messages)}"),
                    sender=sender,
                    text=text,
                    date=msg_dt,
                    has_attachments=has_attach,
                )
            )

        thread_messages.sort(key=lambda m: m.date)
        return MessageThread(subscription_id=self._as_text(subscription_id), subject=subject, messages=thread_messages)

    async def get_letters(self, context: LoginContext, student_id: str) -> list[LetterItem]:
        """Elternbriefe / parent letters (letters/get-letters)."""
        session, _ = self._require_student_session(context, student_id)
        sid = self._opt_int(student_id)

        data = await self._api_call(session, "letters", "get-letters", {}, soft=True)

        rows: list[Any]
        if isinstance(data, list):
            rows = data
        elif isinstance(data, dict):
            rows = data.get("letters") or data.get("data") or []
        else:
            rows = []

        letters: list[LetterItem] = []
        for row in rows:
            if not isinstance(row, dict):
                continue

            title = self._as_text(row.get("title") or row.get("subject") or "Elternbrief")
            sent = self._parse_datetime(row.get("sentDate") or row.get("createdAt") or row.get("date"))

            # Read status is per-student, held in studentStatuses[].
            read = False
            statuses = row.get("studentStatuses") or row.get("recipients")
            if isinstance(statuses, list):
                for status in statuses:
                    if not isinstance(status, dict):
                        continue
                    status_sid = self._opt_int(status.get("studentId") or status.get("id"))
                    if sid is not None and status_sid is not None and status_sid != sid:
                        continue
                    if status.get("readTimestamp") or status.get("statusRead") or status.get("read"):
                        read = True
                        break
            else:
                read = bool(row.get("read") or row.get("readTimestamp"))

            attachments = row.get("attachments")
            attachment_count = len(attachments) if isinstance(attachments, list) else 0
            requires_confirmation = bool(
                row.get("requiresConfirmation")
                or row.get("needsConfirmation")
                or row.get("hasConfirmationRequest")
            )
            sender = self._opt_text(row.get("senderName") or row.get("sender") or row.get("author"))

            letters.append(
                LetterItem(
                    id=self._as_text(row.get("id") or f"letter_{len(letters)}"),
                    title=title,
                    date=sent,
                    read=read,
                    sender=sender,
                    requires_confirmation=requires_confirmation,
                    attachment_count=attachment_count,
                )
            )

        letters.sort(key=lambda letter: (letter.date is not None, letter.date or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
        return letters

    async def _api_login(self, credentials: AuthRequest) -> dict[str, Any]:
        institution_id = credentials.institution_id
        user_id = credentials.user_id

        while True:
            salt_payload = {
                "emailOrUsername": credentials.email,
                "userId": user_id,
                "institutionId": institution_id,
            }
            headers = self._json_headers()

            async with httpx.AsyncClient(timeout=20) as client:
                salt_response = await client.post(GET_SALT_URL, json=salt_payload, headers=headers)
                if salt_response.status_code != 200:
                    raise HTTPException(status_code=401, detail="Konnte Login-Salt nicht laden")

                salt = self._parse_salt_response(salt_response.text)
                hashed = self._pbkdf2_hash_hex(credentials.password, salt)

                login_payload = {
                    "emailOrUsername": credentials.email,
                    "password": credentials.password,
                    "hash": hashed,
                    "mobileApp": False,
                    "userId": user_id,
                    "twoFactorCode": None,
                    "institutionId": institution_id,
                }

                response = await client.post(LOGIN_API_URL, json=login_payload, headers=headers)

            if response.status_code != 200:
                raise HTTPException(status_code=401, detail="Schulmanager Login fehlgeschlagen")

            data = response.json()
            if "multipleAccounts" in data:
                account = self._select_account(data.get("multipleAccounts") or [], credentials.school_id)
                if account is None:
                    raise HTTPException(
                        status_code=400,
                        detail="Mehrere Schulen gefunden. Bitte school_id setzen.",
                    )
                institution_id = self._opt_int(account.get("institutionId"))
                user_id = self._opt_int(account.get("userId"))
                continue

            return data

    def _verify_login_with_browser(self, credentials: AuthRequest) -> None:
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.chrome.service import Service
            from selenium.webdriver.common.by import By
            from selenium.webdriver.common.keys import Keys
            from selenium.webdriver.support import expected_conditions as EC
            from selenium.webdriver.support.ui import WebDriverWait
        except ImportError as exc:
            raise RuntimeError("Selenium ist nicht installiert") from exc

        options = Options()
        if self._settings.selenium_headless:
            options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--window-size=1280,960")

        if self._settings.selenium_driver_path:
            service = Service(self._settings.selenium_driver_path)
            driver = webdriver.Chrome(service=service, options=options)
        else:
            driver = webdriver.Chrome(options=options)

        try:
            timeout = max(self._settings.selenium_login_timeout_seconds, 5)
            driver.get(LOGIN_PAGE_URL)
            wait = WebDriverWait(driver, timeout)
            user_input = wait.until(EC.presence_of_element_located((By.ID, "emailOrUsername")))
            pass_input = wait.until(EC.presence_of_element_located((By.ID, "password")))

            user_input.clear()
            user_input.send_keys(credentials.email)
            pass_input.clear()
            pass_input.send_keys(credentials.password + Keys.RETURN)

            def _logged_in(drv) -> bool:  # type: ignore[no-untyped-def]
                url = drv.current_url or ""
                if "#/modules" in url:
                    return True
                try:
                    if drv.find_elements(By.ID, "accountDropdown"):
                        return True
                except Exception:
                    return False
                return False

            wait.until(_logged_in)
        finally:
            driver.quit()

    async def _discover_bundle_version(self) -> str:
        # Serve a cached value if still fresh. bundleVersion changes only on Schulmanager
        # deploys, and its *content* is not validated by the server, so a stale/dummy value is
        # harmless — this cache just avoids re-scraping big JS bundles on every login.
        ttl = max(self._settings.selenium_bundle_cache_ttl_seconds, 0)
        with self._bundle_lock:
            cached = SeleniumSchulmanagerProvider._bundle_cache
        if cached is not None and (time.monotonic() - cached[1]) < ttl:
            return cached[0]

        discovered = await self._scrape_bundle_version()
        value = discovered or self._settings.selenium_bundle_version
        if not discovered:
            logger.info("bundleVersion discovery failed; using fallback placeholder (server ignores it)")
        with self._bundle_lock:
            SeleniumSchulmanagerProvider._bundle_cache = (value, time.monotonic())
        return value

    async def _scrape_bundle_version(self) -> str | None:
        async with httpx.AsyncClient(timeout=15) as client:
            try:
                response = await client.get(INDEX_URL, headers={"Accept": "text/html"})
                if response.status_code != 200:
                    return None
                html = response.text
            except Exception:
                return None

            scripts = re.findall(r'<script[^>]+src=["\']([^"\']+\.js)["\']', html, re.IGNORECASE)
            scripts += re.findall(
                r'<link[^>]+rel=["\']modulepreload["\'][^>]+href=["\']([^"\']+\.js)["\']',
                html,
                re.IGNORECASE,
            )

            normalized: list[str] = []
            for src in scripts:
                if src.startswith("http"):
                    normalized.append(src)
                elif src.startswith("/"):
                    normalized.append(INDEX_URL.rstrip("/") + src)
                else:
                    normalized.append(INDEX_URL + src.lstrip("./"))

            # Observed bundleVersion values range from 10 to 20 hex chars — don't hard-code 10.
            pattern = re.compile(r'bundleVersion["\']?\s*[:=]\s*["\']([a-f0-9]{8,40})["\']', re.IGNORECASE)
            for js_url in normalized:
                try:
                    js_response = await client.get(js_url)
                    if js_response.status_code != 200:
                        continue
                    match = pattern.search(js_response.text)
                    if match:
                        return match.group(1)
                except Exception:
                    continue

        return None

    async def _api_call(
        self,
        session: SeleniumAccountSession,
        module_name: str,
        endpoint_name: str,
        parameters: dict[str, Any],
        *,
        soft: bool = False,
    ) -> Any:
        """Call a Schulmanager api/calls endpoint.

        Unlike the old implementation this does NOT collapse errors into an empty list: a real
        failure (expired token, wrong endpoint) now raises so it is visible instead of looking
        like "no data". ``soft=True`` is for optional/per-school modules (letters, messenger,
        absences): a genuine endpoint error degrades to ``[]``, but an expired session (401)
        still raises so the client can re-authenticate.
        """
        payload: dict[str, Any] = {
            "requests": [
                {
                    "moduleName": module_name,
                    "endpointName": endpoint_name,
                    "parameters": parameters,
                }
            ],
            "bundleVersion": session.bundle_version,
        }

        headers = self._json_headers() | {"Authorization": f"Bearer {session.token}"}

        try:
            async with httpx.AsyncClient(timeout=25) as client:
                response = await client.post(CALLS_URL, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=504,
                detail=f"Schulmanager nicht erreichbar ({module_name}/{endpoint_name}): {exc}",
            ) from exc

        if response.status_code in (401, 403):
            raise HTTPException(
                status_code=401,
                detail="Schulmanager-Sitzung abgelaufen. Bitte neu einloggen.",
            )
        if response.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=f"Schulmanager api/calls HTTP {response.status_code} ({module_name}/{endpoint_name})",
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Schulmanager lieferte kein JSON ({module_name}/{endpoint_name})",
            ) from exc

        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list) or not results:
            if soft:
                return []
            raise HTTPException(
                status_code=502,
                detail=f"Schulmanager api/calls ohne Ergebnis ({module_name}/{endpoint_name})",
            )

        result = results[0]
        if not isinstance(result, dict):
            if soft:
                return []
            raise HTTPException(
                status_code=502,
                detail=f"Unerwartete api/calls Antwort ({module_name}/{endpoint_name})",
            )

        status = int(result.get("status") or 500)
        if status == 200:
            return result.get("data", [])

        # Inner error: an expired/invalid Schulmanager token always means "re-login".
        if status in (401, 403):
            raise HTTPException(
                status_code=401,
                detail="Schulmanager-Sitzung abgelaufen. Bitte neu einloggen.",
            )

        detail = self._as_text(result.get("error") or result.get("message") or "")
        if soft:
            logger.info("Soft api/calls error %s/%s status=%s %s", module_name, endpoint_name, status, detail)
            return []
        raise HTTPException(
            status_code=502,
            detail=f"Schulmanager api/calls Fehler ({module_name}/{endpoint_name}): status={status} {detail}".strip(),
        )

    async def _get_grade_term_ids(self, session: SeleniumAccountSession, reference_date: date) -> list[int]:
        if session.grade_term_ids is not None:
            return session.grade_term_ids

        parameters = {
            "action": {
                "model": "main/term",
                "action": "findAll",
                "parameters": [
                    {
                        "attributes": ["id", "start", "end"],
                    }
                ],
            },
            "uiState": "main.modules.grades.student",
        }

        rows = await self._api_call(session, "grades", "poqa", parameters, soft=True)

        current_ids: list[int] = []
        other_terms: list[tuple[date, int]] = []

        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                term_id = self._opt_int(row.get("id"))
                term_start = self._parse_date(row.get("start"))
                term_end = self._parse_date(row.get("end"))
                if term_id is None or term_start is None:
                    continue

                if term_end and term_start <= reference_date <= term_end:
                    current_ids.append(term_id)
                else:
                    other_terms.append((term_start, term_id))

        other_terms.sort(key=lambda entry: entry[0], reverse=True)
        ordered = current_ids + [term_id for _, term_id in other_terms]

        # Keep unique order
        unique: list[int] = []
        seen: set[int] = set()
        for term_id in ordered:
            if term_id in seen:
                continue
            seen.add(term_id)
            unique.append(term_id)

        session.grade_term_ids = unique
        return unique

    async def _get_subject_map(self, session: SeleniumAccountSession) -> dict[int, str]:
        if session.subjects_by_id is not None:
            return session.subjects_by_id

        parameters = {
            "action": {
                "model": "main/subject",
                "action": "findAll",
                "parameters": [
                    {
                        "attributes": ["id", "name", "abbreviation"],
                    }
                ],
            },
            "uiState": "main.modules.grades.student",
        }

        rows = await self._api_call(session, "grades", "poqa", parameters, soft=True)
        subjects: dict[int, str] = {}
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                subject_id = self._opt_int(row.get("id"))
                if subject_id is None:
                    continue
                subject_name = self._opt_text(row.get("name") or row.get("abbreviation"))
                if not subject_name:
                    continue
                subjects[subject_id] = subject_name

        session.subjects_by_id = subjects
        return subjects

    async def _get_class_hours_by_key(self, session: SeleniumAccountSession) -> dict[str, dict[str, Any]]:
        if session.class_hours_by_key is not None:
            return session.class_hours_by_key

        rows = await self._api_call(session, "schedules", "get-class-hours", {}, soft=True)
        mapping: dict[str, dict[str, Any]] = {}
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                id_candidates = (
                    self._opt_int(row.get("id")),
                    self._opt_int(row.get("classHourId")),
                    self._opt_int(row.get("hourId")),
                )
                for hour_id in id_candidates:
                    if hour_id is None:
                        continue
                    mapping[f"id:{hour_id}"] = row

                raw_number_values = (
                    row.get("number"),
                    row.get("classHourNumber"),
                    row.get("hourNumber"),
                    row.get("name"),
                    row.get("label"),
                )
                for raw_number in raw_number_values:
                    number_text = self._opt_text(raw_number)
                    if not number_text:
                        continue
                    mapping[f"no:{number_text}"] = row
                    digit_match = re.search(r"\d+", number_text)
                    if digit_match:
                        mapping[f"no:{digit_match.group(0)}"] = row

        session.class_hours_by_key = mapping
        return mapping

    def _coerce_grades_payload(self, rows: Any) -> dict[str, Any] | None:
        def looks_like_grades_payload(payload: Any) -> bool:
            return isinstance(payload, dict) and any(
                key in payload for key in ("gradingEvents", "courses", "typePresets", "subjects")
            )

        if looks_like_grades_payload(rows):
            return rows

        if isinstance(rows, dict):
            nested = rows.get("data")
            if looks_like_grades_payload(nested):
                return nested

        if isinstance(rows, list):
            for entry in rows:
                if looks_like_grades_payload(entry):
                    return entry
                if isinstance(entry, dict):
                    nested = entry.get("data")
                    if looks_like_grades_payload(nested):
                        return nested

        return None

    def _parse_grade_items(self, payload: dict[str, Any]) -> list[GradeItem]:
        # Subject lookup cache from API (id -> subject name).
        subject_map = payload.get("_subject_map")
        if not isinstance(subject_map, dict):
            subject_map = {}

        courses = payload.get("courses") or []
        grading_events = payload.get("gradingEvents") or []
        type_presets = payload.get("typePresets") or []

        course_map: dict[int, dict[str, Any]] = {
            int(course.get("id")): course
            for course in courses
            if isinstance(course, dict) and course.get("id") is not None
        }
        type_map: dict[int, str] = {}
        for preset in type_presets:
            if not isinstance(preset, dict):
                continue
            grade_type = preset.get("gradeType")
            if isinstance(grade_type, dict) and grade_type.get("id") is not None:
                type_map[int(grade_type.get("id"))] = self._as_text(
                    grade_type.get("name") or grade_type.get("abbreviation") or "Note"
                )

        result: list[GradeItem] = []
        if isinstance(grading_events, list) and grading_events:
            for event in grading_events:
                if not isinstance(event, dict):
                    continue

                course_id = self._opt_int(event.get("courseId"))
                course = course_map.get(course_id) if course_id is not None else None
                subject = self._derive_grade_subject(event, course, subject_map)
                grade_type_name = type_map.get(self._opt_int(event.get("gradeTypeId")) or -1, "Note")
                event_date = self._parse_date(event.get("date"))
                event_topic = self._as_text(event.get("topic") or "")
                event_weighting = self._opt_float(event.get("weighting"))

                grades = event.get("grades")
                if isinstance(grades, list) and grades:
                    grade_candidates = [entry for entry in grades if isinstance(entry, dict)]
                elif event.get("value") not in (None, ""):
                    grade_candidates = [event]
                else:
                    grade_candidates = []

                for grade_data in grade_candidates:
                    raw_value = (
                        grade_data.get("value")
                        or grade_data.get("displayValue")
                        or grade_data.get("originalValue")
                    )
                    if raw_value in (None, ""):
                        continue
                    value_text = self._normalize_grade_value(raw_value)
                    grade_date = self._parse_date(grade_data.get("date")) or event_date
                    grade_weighting = self._opt_float(grade_data.get("weighting")) or event_weighting
                    comment = self._as_text(
                        grade_data.get("topic")
                        or grade_data.get("comment")
                        or event_topic
                        or grade_type_name
                    )

                    result.append(
                        GradeItem(
                            subject=subject,
                            grade=value_text,
                            weight=grade_weighting,
                            date=grade_date,
                            comment=comment,
                        )
                    )

            if result:
                return result

        # Fallback for already grouped grade structures.
        subjects = payload.get("subjects")
        if isinstance(subjects, dict):
            for subject_data in subjects.values():
                if not isinstance(subject_data, dict):
                    continue
                subject_name = self._as_text(subject_data.get("name") or "Fach")
                categories = subject_data.get("grades") or {}
                if not isinstance(categories, dict):
                    continue
                for category_name, grade_list in categories.items():
                    if not isinstance(grade_list, list):
                        continue
                    for grade_data in grade_list:
                        if not isinstance(grade_data, dict):
                            continue
                        raw_value = (
                            grade_data.get("display_value")
                            or grade_data.get("original_value")
                            or grade_data.get("value")
                        )
                        if raw_value in (None, ""):
                            continue
                        result.append(
                            GradeItem(
                                subject=subject_name,
                                grade=self._normalize_grade_value(raw_value),
                                weight=self._opt_float(grade_data.get("weighting")),
                                date=self._parse_date(grade_data.get("date")),
                                comment=self._as_text(grade_data.get("topic") or category_name or "Note"),
                            )
                        )

        return result

    def _derive_grade_subject(
        self,
        event: dict[str, Any],
        course: dict[str, Any] | None,
        subject_map: dict[int, str],
    ) -> str:
        if isinstance(course, dict):
            subject_id = self._opt_int(course.get("subjectId"))
            if subject_id is not None and subject_id in subject_map:
                return subject_map[subject_id]

            subject = course.get("subject")
            if isinstance(subject, dict):
                subject_name = self._opt_text(subject.get("name") or subject.get("abbreviation"))
                if subject_name:
                    return subject_name
            subject_name = self._opt_text(
                course.get("name")
                or course.get("subjectAlias")
                or course.get("subjectText")
            )
            if subject_name:
                return subject_name

        subject = event.get("subject")
        if isinstance(subject, dict):
            subject_name = self._opt_text(subject.get("name") or subject.get("abbreviation"))
            if subject_name:
                return subject_name
        elif subject is not None:
            subject_name = self._opt_text(subject)
            if subject_name:
                return subject_name

        return self._as_text(event.get("subjectText") or event.get("topic") or "Fach")

    def logout(self, account_id: str) -> None:
        """Drop the in-memory Schulmanager session (token) for an account."""
        with self._lock:
            self._sessions.pop(account_id, None)

    def _require_session(self, context: LoginContext) -> SeleniumAccountSession:
        with self._lock:
            session = self._sessions.get(context.account_id)
        if session is None:
            raise HTTPException(
                status_code=401,
                detail="Schulmanager-Sitzung nicht gefunden (Server-Neustart?). Bitte neu einloggen.",
            )
        return session

    def _require_student_session(self, context: LoginContext, student_id: str) -> tuple[SeleniumAccountSession, dict[str, Any]]:
        session = self._require_session(context)
        student_raw = session.students_by_id.get(student_id)
        if student_raw is None:
            raise HTTPException(status_code=404, detail="Student nicht gefunden")
        return session, student_raw

    @staticmethod
    def _json_headers() -> dict[str, str]:
        return {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json;charset=UTF-8",
            "Origin": "https://login.schulmanager-online.de",
            "Referer": "https://login.schulmanager-online.de/",
            "User-Agent": "SchulmanagerAPI/0.1",
        }

    def _extract_students(self, user: dict[str, Any], school_name: str) -> dict[str, dict[str, Any]]:
        students: dict[str, dict[str, Any]] = {}

        parents = user.get("associatedParents") or []
        if isinstance(parents, list):
            for parent in parents:
                if not isinstance(parent, dict):
                    continue
                student = parent.get("student")
                self._register_student_candidate(students, student, school_name)

        for key in ("associatedStudents", "students", "children", "associatedChildren"):
            value = user.get(key)
            if not isinstance(value, list):
                continue
            for candidate in value:
                self._register_student_candidate(students, candidate, school_name)

        for key in ("student", "associatedStudent", "child"):
            self._register_student_candidate(students, user.get(key), school_name)

        # Fallback for direct student accounts where user itself is the student object.
        if self._is_probably_student_user(user):
            self._register_student_candidate(students, user, school_name, allow_user_id_fallback=True)

        return students

    def _register_student_candidate(
        self,
        students: dict[str, dict[str, Any]],
        candidate: Any,
        school_name: str,
        allow_user_id_fallback: bool = False,
    ) -> None:
        if not isinstance(candidate, dict):
            return

        # Wrapper objects often contain nested student payloads.
        wrapped = candidate.get("student")
        if isinstance(wrapped, dict):
            candidate = wrapped

        sid = self._as_text(candidate.get("id") or candidate.get("studentId"))
        if not sid and allow_user_id_fallback:
            sid = self._as_text(candidate.get("userId") or candidate.get("id"))
        if not sid:
            return

        first_name = self._as_text(candidate.get("firstname") or candidate.get("firstName") or "")
        last_name = self._as_text(candidate.get("lastname") or candidate.get("lastName") or "")
        if not first_name and not last_name:
            full_name = self._opt_text(candidate.get("name") or candidate.get("displayName") or "")
            if full_name:
                first_name, last_name = self._split_name(full_name)

        class_id = self._opt_int(candidate.get("classId") or candidate.get("schoolClassId"))
        class_name = self._as_text(candidate.get("className") or candidate.get("class") or "")
        resolved_school = self._as_text(
            candidate.get("schoolName")
            or candidate.get("institutionName")
            or school_name
        )

        students[sid] = {
            "id": sid,
            "firstname": first_name,
            "lastname": last_name,
            "classId": class_id,
            "className": class_name,
            "schoolName": resolved_school or school_name,
        }

    def _is_probably_student_user(self, user: dict[str, Any]) -> bool:
        if self._opt_int(user.get("classId")) is not None:
            return True
        if self._opt_text(user.get("className")):
            return True

        roles = user.get("roles") or user.get("userRoles") or []
        if isinstance(roles, list):
            for role in roles:
                if isinstance(role, str) and "student" in role.lower():
                    return True
                if isinstance(role, dict):
                    role_text = self._as_text(
                        role.get("name")
                        or role.get("type")
                        or role.get("role")
                        or ""
                    )
                    if "student" in role_text.lower():
                        return True

        account_type = self._opt_text(user.get("type") or user.get("accountType") or "")
        if account_type and "student" in account_type.lower():
            return True
        return False

    @staticmethod
    def _split_name(name: str) -> tuple[str, str]:
        parts = [part for part in name.strip().split(" ") if part]
        if not parts:
            return "", ""
        if len(parts) == 1:
            return parts[0], ""
        return parts[0], " ".join(parts[1:])

    def _extract_school_name(self, user: dict[str, Any], credentials: AuthRequest) -> str:
        institution = user.get("institution")
        if isinstance(institution, dict):
            name = self._opt_text(institution.get("name"))
            if name:
                return name

        if credentials.school_id:
            return credentials.school_id
        return "Schule"

    def _student_model(self, raw: dict[str, Any]) -> Student:
        class_name = self._as_text(raw.get("className") or "")
        class_id = raw.get("classId")
        if not class_name and class_id is not None:
            class_name = f"class_{class_id}"

        return Student(
            id=self._as_text(raw.get("id") or ""),
            first_name=self._as_text(raw.get("firstname") or ""),
            last_name=self._as_text(raw.get("lastname") or ""),
            class_name=class_name or "unbekannt",
            school_name=self._as_text(raw.get("schoolName") or "Schule"),
        )

    def _student_payload(self, raw: dict[str, Any]) -> dict[str, Any]:
        class_id = self._opt_int(raw.get("classId"))
        return {
            "id": int(self._as_text(raw.get("id") or "0")),
            "firstname": self._as_text(raw.get("firstname") or ""),
            "lastname": self._as_text(raw.get("lastname") or ""),
            "classId": class_id,
            "class": {
                "id": class_id,
                "name": self._opt_text(raw.get("className")),
                "gradeLevels": None,
                "isCourseSystem": None,
            },
        }

    def _parse_schedule_lesson(
        self,
        row: dict[str, Any],
        class_hours_by_key: dict[str, dict[str, Any]],
    ) -> tuple[date | None, Lesson | None]:
        start_dt, end_dt = self._extract_schedule_datetimes(row)

        lesson_date = self._parse_date(row.get("date"))
        if lesson_date is None and start_dt is not None:
            lesson_date = start_dt.date()
        if lesson_date is None:
            return None, None

        subject = self._extract_subject_text(row)
        teacher = self._extract_teacher_text(row)
        room = self._extract_room_text(row)

        class_hour = self._extract_class_hour_reference(row)
        start_time, end_time = self._resolve_class_hour_times(
            class_hour=class_hour,
            lesson_date=lesson_date,
            class_hours_by_key=class_hours_by_key,
        )
        if not start_time:
            start_time = self._as_text(start_dt.strftime("%H:%M") if start_dt else "08:00")
        if not end_time:
            end_time = self._as_text(end_dt.strftime("%H:%M") if end_dt else "08:45")

        lesson_type = self._as_text(row.get("type") or "")
        change_type = self._map_change_type(lesson_type)
        note = self._opt_text(row.get("substitutionText") or row.get("comment"))
        subject = self._normalize_schedule_subject(subject, row=row, lesson_type=lesson_type, note=note)

        return (
            lesson_date,
            Lesson(
                start_time=start_time,
                end_time=end_time,
                subject=subject,
                teacher=teacher,
                room=room,
                change_type=change_type,
                note=note,
            ),
        )

    def _normalize_schedule_subject(
        self,
        subject: str,
        *,
        row: dict[str, Any],
        lesson_type: str,
        note: str | None,
    ) -> str:
        text = self._as_text(subject)
        if text and text.casefold() not in {"unbekannt", "unknown", "-", "n/a"}:
            return text

        for source in self._schedule_sources(row):
            for field in ("title", "topic", "name", "eventName", "subjectText"):
                value = self._opt_text(source.get(field))
                if value and value.casefold() not in {"unbekannt", "unknown", "-", "n/a"}:
                    return value

        lesson_type_norm = lesson_type.casefold()
        if lesson_type_norm in {"event", "info"}:
            return "Information"
        if note:
            return "Information"
        return "Fach"

    def _merge_parallel_day_lessons(self, lessons: list[Lesson]) -> list[Lesson]:
        if not lessons:
            return []

        grouped: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        order: list[tuple[str, str, str, str]] = []

        for lesson in lessons:
            key = (
                lesson.start_time,
                lesson.end_time,
                self._lesson_key_text(lesson.subject),
                lesson.change_type.value if lesson.change_type else "",
            )
            if key not in grouped:
                grouped[key] = {
                    "lesson": lesson,
                    "teachers": [],
                    "rooms": [],
                    "notes": [],
                }
                order.append(key)

            bucket = grouped[key]
            self._append_unique_text(bucket["teachers"], lesson.teacher)
            self._append_unique_text(bucket["rooms"], lesson.room)
            self._append_unique_text(bucket["notes"], lesson.note)

        merged: list[Lesson] = []
        for key in order:
            bucket = grouped[key]
            base: Lesson = bucket["lesson"]
            merged.append(
                Lesson(
                    start_time=base.start_time,
                    end_time=base.end_time,
                    subject=base.subject,
                    teacher=self._join_texts(bucket["teachers"], ", ", sort_values=True),
                    room=self._join_texts(bucket["rooms"], ", ", sort_values=True),
                    change_type=base.change_type,
                    note=self._join_texts(bucket["notes"], " | ", sort_values=False),
                )
            )

        merged.sort(
            key=lambda item: (
                item.start_time,
                self._lesson_key_text(item.subject),
                self._lesson_key_text(item.teacher or ""),
                self._lesson_key_text(item.room or ""),
            )
        )
        return merged

    @staticmethod
    def _lesson_key_text(value: str) -> str:
        return re.sub(r"\s+", "", value.casefold())

    @staticmethod
    def _append_unique_text(target: list[str], value: str | None) -> None:
        text = str(value or "").strip()
        if not text:
            return
        if text in target:
            return
        target.append(text)

    @staticmethod
    def _join_texts(values: list[str], separator: str, *, sort_values: bool) -> str | None:
        if not values:
            return None
        cleaned = [value.strip() for value in values if value and value.strip()]
        if not cleaned:
            return None
        if sort_values:
            cleaned = sorted(set(cleaned), key=lambda item: item.casefold())
        else:
            unique: list[str] = []
            for item in cleaned:
                if item in unique:
                    continue
                unique.append(item)
            cleaned = unique
        return separator.join(cleaned)

    def _extract_schedule_datetimes(self, row: dict[str, Any]) -> tuple[datetime | None, datetime | None]:
        start_dt: datetime | None = None
        end_dt: datetime | None = None

        for source in self._schedule_sources(row):
            for start_field in ("start", "startDate", "startAt"):
                if start_dt is not None:
                    break
                start_dt = self._parse_datetime(source.get(start_field))
            for end_field in ("end", "endDate", "endAt"):
                if end_dt is not None:
                    break
                end_dt = self._parse_datetime(source.get(end_field))
            if start_dt is not None and end_dt is not None:
                break

        return start_dt, end_dt

    def _extract_class_hour_reference(self, row: dict[str, Any]) -> dict[str, Any]:
        for source in self._schedule_sources(row):
            class_hour = source.get("classHour")
            if isinstance(class_hour, dict):
                return class_hour
            class_hours = source.get("classHours")
            if isinstance(class_hours, list):
                first = class_hours[0] if class_hours else None
                if isinstance(first, dict):
                    return first

            hour_ref: dict[str, Any] = {}
            hour_id = self._opt_int(source.get("classHourId") or source.get("hourId"))
            if hour_id is not None:
                hour_ref["id"] = hour_id
            hour_number = self._opt_text(
                source.get("classHourNumber")
                or source.get("hourNumber")
                or source.get("classHour")
                or source.get("hour")
            )
            if hour_number:
                hour_ref["number"] = hour_number
            if hour_ref:
                return hour_ref

        return {}

    def _schedule_sources(self, row: dict[str, Any]) -> tuple[dict[str, Any], ...]:
        actual = row.get("actualLesson") if isinstance(row.get("actualLesson"), dict) else {}
        original_lessons = row.get("originalLessons") if isinstance(row.get("originalLessons"), list) else []
        original = original_lessons[0] if original_lessons and isinstance(original_lessons[0], dict) else {}
        return actual, row, original

    def _resolve_class_hour_times(
        self,
        *,
        class_hour: dict[str, Any],
        lesson_date: date,
        class_hours_by_key: dict[str, dict[str, Any]],
    ) -> tuple[str | None, str | None]:
        direct_start = self._normalize_hhmm(
            self._opt_text(
                class_hour.get("from")
                or class_hour.get("start")
                or class_hour.get("startTime")
            )
        )
        direct_end = self._normalize_hhmm(
            self._opt_text(
                class_hour.get("until")
                or class_hour.get("end")
                or class_hour.get("endTime")
            )
        )
        if direct_start and direct_end:
            return direct_start, direct_end

        hour_id = self._opt_int(class_hour.get("id") or class_hour.get("classHourId"))
        hour_number = self._opt_text(
            class_hour.get("number")
            or class_hour.get("classHourNumber")
            or class_hour.get("hourNumber")
            or class_hour.get("name")
            or class_hour.get("label")
        )
        if hour_number:
            digit_match = re.search(r"\d+", hour_number)
            if digit_match:
                hour_number = digit_match.group(0)

        source = None
        if hour_id is not None:
            source = class_hours_by_key.get(f"id:{hour_id}")
        if source is None and hour_number:
            source = class_hours_by_key.get(f"no:{hour_number}")
        if not isinstance(source, dict):
            return None, None

        weekday = lesson_date.weekday()  # monday=0
        start = (
            self._pick_time_by_day(
                source.get("fromByDay")
                or source.get("startByDay")
                or source.get("startTimesByDay"),
                weekday,
            )
            or self._opt_text(source.get("from") or source.get("start") or source.get("startTime"))
        )
        end = (
            self._pick_time_by_day(
                source.get("untilByDay")
                or source.get("endByDay")
                or source.get("endTimesByDay"),
                weekday,
            )
            or self._opt_text(source.get("until") or source.get("end") or source.get("endTime"))
        )

        return self._normalize_hhmm(start), self._normalize_hhmm(end)

    def _pick_time_by_day(self, values: Any, weekday: int) -> str | None:
        if isinstance(values, dict):
            keys: tuple[Any, ...] = (
                weekday,
                str(weekday),
                weekday + 1,
                str(weekday + 1),
                ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")[weekday],
                ("mon", "tue", "wed", "thu", "fri", "sat", "sun")[weekday],
            )
            for key in keys:
                if key not in values:
                    continue
                text = self._opt_text(values.get(key))
                if text:
                    return text
            return None

        if not isinstance(values, list):
            return None

        for index in (weekday, weekday + 1):
            if index < 0 or index >= len(values):
                continue
            text = self._opt_text(values[index])
            if text:
                return text
        return None

    def _normalize_hhmm(self, value: str | None) -> str | None:
        if not value:
            return None
        text = value.strip()
        if not text:
            return None

        match = re.match(r"^\s*(\d{1,2})[:.](\d{2})", text)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2))
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return f"{hour:02d}:{minute:02d}"

        digits = re.sub(r"\D", "", text)
        if len(digits) >= 4:
            hour = int(digits[:2])
            minute = int(digits[2:4])
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return f"{hour:02d}:{minute:02d}"

        return None

    def _extract_subject_text(self, row: dict[str, Any]) -> str:
        actual = row.get("actualLesson") if isinstance(row.get("actualLesson"), dict) else {}
        original_lessons = row.get("originalLessons") if isinstance(row.get("originalLessons"), list) else []
        original = original_lessons[0] if original_lessons and isinstance(original_lessons[0], dict) else {}

        for source in (actual, row, original):
            subject = source.get("subject") if isinstance(source, dict) else None
            if isinstance(subject, dict):
                name = self._opt_text(subject.get("abbreviation") or subject.get("name"))
                if name:
                    return name
            elif subject is not None:
                text = self._opt_text(subject)
                if text:
                    return text

        return self._as_text(row.get("subjectText") or "Unbekannt")

    def _extract_teacher_text(self, row: dict[str, Any]) -> str | None:
        actual = row.get("actualLesson") if isinstance(row.get("actualLesson"), dict) else {}
        original_lessons = row.get("originalLessons") if isinstance(row.get("originalLessons"), list) else []
        original = original_lessons[0] if original_lessons and isinstance(original_lessons[0], dict) else {}

        for source in (actual, row, original):
            teachers = source.get("teachers") if isinstance(source, dict) else None
            if isinstance(teachers, list) and teachers:
                first = teachers[0]
                if isinstance(first, dict):
                    text = self._opt_text(first.get("abbreviation") or first.get("name"))
                    if text:
                        return text
                else:
                    text = self._opt_text(first)
                    if text:
                        return text

        return None

    def _extract_room_text(self, row: dict[str, Any]) -> str | None:
        actual = row.get("actualLesson") if isinstance(row.get("actualLesson"), dict) else {}
        original_lessons = row.get("originalLessons") if isinstance(row.get("originalLessons"), list) else []
        original = original_lessons[0] if original_lessons and isinstance(original_lessons[0], dict) else {}

        for source in (actual, row, original):
            room = source.get("room") if isinstance(source, dict) else None
            if isinstance(room, dict):
                text = self._opt_text(room.get("name"))
                if text:
                    return text
            elif room is not None:
                text = self._opt_text(room)
                if text:
                    return text

        return None

    @staticmethod
    def _map_change_type(lesson_type: str) -> LessonChangeType | None:
        mapping = {
            "cancelledLesson": LessonChangeType.CANCELLATION,
            "substitution": LessonChangeType.SUBSTITUTION,
            "teacherChange": LessonChangeType.SUBSTITUTION,
            "specialLesson": LessonChangeType.SUBSTITUTION,
            "roomChange": LessonChangeType.ROOM_CHANGE,
            "exam": LessonChangeType.EXAM,
            "event": LessonChangeType.INFO,
        }
        return mapping.get(lesson_type)

    @staticmethod
    def _normalize_grade_value(value: Any) -> str:
        text = str(value).strip()
        if "~" in text:
            return text.split("~", 1)[1]
        return text

    @staticmethod
    def _pbkdf2_hash_hex(password: str, salt: str) -> str:
        # Schulmanager's web client derives the hash over UTF-8 bytes; latin-1 (the old value)
        # crashes or mismatches for umlaut/non-ASCII passwords.
        pw_bytes = password.encode("utf-8")
        salt_bytes = salt.encode("utf-8")
        derived = hashlib.pbkdf2_hmac("sha512", pw_bytes, salt_bytes, 99999, dklen=512)
        return derived.hex()

    def _parse_salt_response(self, text: str) -> str:
        try:
            parsed = json.loads(text)
            if isinstance(parsed, str):
                return parsed
            return str(parsed)
        except json.JSONDecodeError:
            cleaned = text.strip().strip('"')
            if not cleaned:
                raise HTTPException(status_code=401, detail="Ungueltige Salt-Antwort vom Login-Server")
            return cleaned

    def _select_account(self, accounts: list[Any], school_id: str | None) -> dict[str, Any] | None:
        if not accounts:
            return None

        if not school_id:
            first = accounts[0]
            return first if isinstance(first, dict) else None

        school_id_norm = school_id.strip().lower()
        for account in accounts:
            if not isinstance(account, dict):
                continue
            institution_id = self._opt_text(account.get("institutionId"))
            name = self._opt_text(account.get("institutionName") or account.get("institution") or "")
            if institution_id and institution_id.lower() == school_id_norm:
                return account
            if name and name.lower() == school_id_norm:
                return account

        return None

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        # Naive (offset-less) Schulmanager timestamps are the school's local wall clock, so
        # attach the school timezone rather than mislabelling them UTC (which shifts events 1-2h).
        if value is None:
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=_school_tz())

        text = str(value).strip()
        if not text:
            return None

        if text.endswith("Z"):
            text = text[:-1] + "+00:00"

        try:
            parsed = datetime.fromisoformat(text)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=_school_tz())
        except ValueError:
            try:
                parsed = datetime.strptime(text[:19], "%Y-%m-%dT%H:%M:%S")
                return parsed.replace(tzinfo=_school_tz())
            except ValueError:
                return None

    @classmethod
    def _parse_date(cls, value: Any) -> date | None:
        if value is None:
            return None
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        if isinstance(value, datetime):
            return value.date()

        text = str(value).strip()
        if not text:
            return None

        if "T" in text:
            dt = cls._parse_datetime(text)
            return dt.date() if dt else None

        for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue

        return None

    @staticmethod
    def _opt_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _opt_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _as_text(value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @classmethod
    def _opt_text(cls, value: Any) -> str | None:
        text = cls._as_text(value)
        return text if text else None
