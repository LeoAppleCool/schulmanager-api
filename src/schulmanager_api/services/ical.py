from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any


def _escape(value: str) -> str:
    """Escape special characters for ICS text values."""
    value = value.replace("\\", "\\\\")
    value = value.replace(";", "\\;")
    value = value.replace(",", "\\,")
    value = value.replace("\n", "\\n")
    return value


def _fold(line: str) -> str:
    """Fold long lines per RFC 5545 (max 75 octets, fold with CRLF + SPACE)."""
    if len(line.encode("utf-8")) <= 75:
        return line
    result: list[str] = []
    current = ""
    for char in line:
        candidate = current + char
        if len(candidate.encode("utf-8")) > 75:
            result.append(current)
            current = " " + char
        else:
            current = candidate
    result.append(current)
    return "\r\n".join(result)


def _dt_stamp(dt: datetime) -> str:
    utc = dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return utc.strftime("%Y%m%dT%H%M%SZ")


def _date_value(d: date) -> str:
    return d.strftime("%Y%m%d")


def build_ics(
    student_name: str,
    schedule_days: list[Any],
    exams: list[Any],
    events: list[Any],
    *,
    horizon_days: int = 90,
) -> bytes:
    today = date.today()
    cutoff = today + timedelta(days=horizon_days)

    uid_counter = [0]

    def next_uid(prefix: str) -> str:
        uid_counter[0] += 1
        return f"{prefix}-{uid_counter[0]}@schulmanager-api"

    lines: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:-//Schulmanager API//{_escape(student_name)}//DE",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(student_name)} - Schulmanager",
    ]

    # Schedule lessons
    for day_raw in schedule_days:
        if not isinstance(day_raw, dict):
            continue
        try:
            day_date = date.fromisoformat(str(day_raw.get("date") or "")[:10])
        except ValueError:
            continue
        if day_date < today or day_date > cutoff:
            continue
        for lesson in (day_raw.get("lessons") or []):
            if not isinstance(lesson, dict):
                continue
            try:
                sh, sm = map(int, str(lesson.get("start_time", "00:00")).split(":")[:2])
                eh, em = map(int, str(lesson.get("end_time", "00:00")).split(":")[:2])
            except (ValueError, AttributeError):
                continue
            start_dt = datetime(day_date.year, day_date.month, day_date.day, sh, sm, tzinfo=timezone.utc)
            end_dt = datetime(day_date.year, day_date.month, day_date.day, eh, em, tzinfo=timezone.utc)
            subject = str(lesson.get("subject") or "Fach")
            teacher = str(lesson.get("teacher") or "")
            room = str(lesson.get("room") or "")
            change_type = str(lesson.get("change_type") or "")
            note = str(lesson.get("note") or "")
            summary_parts = [subject]
            if change_type:
                summary_parts.append(f"[{change_type.upper()}]")
            desc_parts = []
            if teacher:
                desc_parts.append(f"Lehrer: {teacher}")
            if room:
                desc_parts.append(f"Raum: {room}")
            if note:
                desc_parts.append(f"Hinweis: {note}")
            lines += [
                "BEGIN:VEVENT",
                f"UID:{next_uid('lesson')}",
                f"DTSTART:{_dt_stamp(start_dt)}",
                f"DTEND:{_dt_stamp(end_dt)}",
                _fold(f"SUMMARY:{_escape(' '.join(summary_parts))}"),
            ]
            if desc_parts:
                lines.append(_fold(f"DESCRIPTION:{_escape(chr(10).join(desc_parts))}"))
            if room:
                lines.append(_fold(f"LOCATION:{_escape(room)}"))
            lines.append("END:VEVENT")

    # Exams (all-day events)
    for exam in exams:
        if not isinstance(exam, dict):
            continue
        try:
            exam_date = date.fromisoformat(str(exam.get("date") or "")[:10])
        except ValueError:
            continue
        if exam_date < today or exam_date > cutoff:
            continue
        subject = str(exam.get("subject") or "Pruefung")
        topic = str(exam.get("topic") or "")
        summary = f"Pruefung: {subject}"
        lines += [
            "BEGIN:VEVENT",
            f"UID:{next_uid('exam')}",
            f"DTSTART;VALUE=DATE:{_date_value(exam_date)}",
            f"DTEND;VALUE=DATE:{_date_value(exam_date + timedelta(days=1))}",
            _fold(f"SUMMARY:{_escape(summary)}"),
        ]
        if topic:
            lines.append(_fold(f"DESCRIPTION:{_escape(topic)}"))
        lines.append("END:VEVENT")

    # Events
    for event in events:
        if not isinstance(event, dict):
            continue
        start_str = str(event.get("start") or "")
        end_str = str(event.get("end") or "")
        if not start_str or not end_str:
            continue
        try:
            # Parse ISO format (with potential Z suffix)
            start_str = start_str.replace("Z", "+00:00")
            end_str = end_str.replace("Z", "+00:00")
            event_start = datetime.fromisoformat(start_str)
            event_end = datetime.fromisoformat(end_str)
        except ValueError:
            continue
        if event_start.date() > cutoff or event_end.date() < today:
            continue
        title = str(event.get("title") or "Schultermin")
        location = str(event.get("location") or "")
        description = str(event.get("description") or "")
        lines += [
            "BEGIN:VEVENT",
            f"UID:{next_uid('event')}",
            f"DTSTART:{_dt_stamp(event_start)}",
            f"DTEND:{_dt_stamp(event_end)}",
            _fold(f"SUMMARY:{_escape(title)}"),
        ]
        if description:
            lines.append(_fold(f"DESCRIPTION:{_escape(description)}"))
        if location:
            lines.append(_fold(f"LOCATION:{_escape(location)}"))
        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines).encode("utf-8")
