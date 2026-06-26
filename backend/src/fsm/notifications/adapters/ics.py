"""iCalendar (.ics) builder for appointment notifications.

Builds a minimal but valid VCALENDAR/VEVENT string using only the stdlib.
No third-party dependencies are introduced.
"""
from __future__ import annotations

from datetime import timezone


def build_ics(appointment) -> str:
    """Return a VCALENDAR string with one VEVENT describing the appointment.

    UID is deterministic: fsm-{appointment_id}@fsm.local. DTSTART/DTEND are
    expressed in UTC using the Zulu suffix (…Z). DTSTAMP is set to the same
    value as DTSTART so the output is reproducible in tests.
    """
    start = appointment.time_range.start.astimezone(timezone.utc)
    end = appointment.time_range.end.astimezone(timezone.utc)

    def _fmt(dt) -> str:
        return dt.strftime("%Y%m%dT%H%M%SZ")

    uid = f"fsm-{appointment.id}@fsm.local"
    dtstart = _fmt(start)
    dtend = _fmt(end)
    dtstamp = _fmt(start)

    return (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//FSM//Field Service Management//EN\r\n"
        "BEGIN:VEVENT\r\n"
        f"UID:{uid}\r\n"
        f"DTSTAMP:{dtstamp}\r\n"
        f"DTSTART:{dtstart}\r\n"
        f"DTEND:{dtend}\r\n"
        "SUMMARY:Field service appointment\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
