"""iCalendar (.ics) builder for appointment notifications.

Builds a minimal but valid VCALENDAR/VEVENT string using only the stdlib.
"""
from __future__ import annotations

from datetime import timezone


_FOLD_LIMIT = 75


def _fold(line: str) -> str:
    """Fold a content line per RFC 5545 3.1: no physical line exceeds 75 octets.

    Splits on UTF-8 octet boundaries only (never inside a multi-byte character) and prefixes
    each continuation with a single space, which itself counts toward that line's 75-octet cap.
    """
    encoded = line.encode("utf-8")
    if len(encoded) <= _FOLD_LIMIT:
        return line

    parts: list[str] = []
    first = True
    while encoded:
        limit = _FOLD_LIMIT if first else _FOLD_LIMIT - 1
        cut = min(limit, len(encoded))
        while cut > 0:
            try:
                chunk = encoded[:cut].decode("utf-8")
                break
            except UnicodeDecodeError:
                cut -= 1
        parts.append(chunk)
        encoded = encoded[cut:]
        first = False
    return "\r\n ".join(parts)


def _escape_text(value: str) -> str:
    """Escape an iCalendar TEXT value per RFC 5545: backslash, semicolon, comma, newlines."""
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def build_ics(appointment, context) -> str:
    """Return a VCALENDAR string with one VEVENT describing the appointment.

    UID is deterministic: fsm-{appointment_id}@fsm.local. DTSTART/DTEND are
    expressed in UTC using the Zulu suffix (…Z). DTSTAMP is set to the same
    value as DTSTART so the output is reproducible in tests.

    context is a duck-typed AppointmentContext supplying customer/problem enrichment: SUMMARY
    comes from context.summary_line(), LOCATION from the service address, and DESCRIPTION
    carries the problem plus a phone contact line when present.
    """
    start = appointment.time_range.start.astimezone(timezone.utc)
    end = appointment.time_range.end.astimezone(timezone.utc)

    def _fmt(dt) -> str:
        return dt.strftime("%Y%m%dT%H%M%SZ")

    uid = f"fsm-{appointment.id}@fsm.local"
    dtstart = _fmt(start)
    dtend = _fmt(end)
    dtstamp = _fmt(start)

    problem = (context.problem_description or "").strip()
    phone = (context.customer_phone or "").strip()
    address = (context.service_address or "").strip()

    description_text = "\n".join(
        part for part in (problem, f"Phone: {phone}" if phone else "") if part
    )
    summary = _fold(f"SUMMARY:{_escape_text(context.summary_line())}")
    location_line = f"{_fold(f'LOCATION:{_escape_text(address)}')}\r\n" if address else ""
    description_line = (
        f"{_fold(f'DESCRIPTION:{_escape_text(description_text)}')}\r\n" if description_text else ""
    )

    return (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//FSM//Field Service Management//EN\r\n"
        "BEGIN:VEVENT\r\n"
        f"UID:{uid}\r\n"
        f"DTSTAMP:{dtstamp}\r\n"
        f"DTSTART:{dtstart}\r\n"
        f"DTEND:{dtend}\r\n"
        f"{summary}\r\n"
        f"{location_line}"
        f"{description_line}"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
