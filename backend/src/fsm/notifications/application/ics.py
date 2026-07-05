"""iCalendar (.ics) builder for appointment notifications.

Builds a minimal but valid VCALENDAR/VEVENT string using only the stdlib.
"""
from __future__ import annotations

from datetime import timezone

from fsm.notifications.ports.appointment_context import AppointmentContextView

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


def build_ics(
    appointment,
    context: AppointmentContextView,
    *,
    uid: str,
    method: str = "REQUEST",
    organizer: str | None = None,
    attendee: str | None = None,
) -> str:
    """Return a VCALENDAR string with one VEVENT describing the appointment.

    uid is the event's UID line verbatim; the caller supplies it because the identity scheme
    tying an appointment to its calendar event is owned by the scheduling domain, which the
    notifications context may not import. DTSTART/DTEND/DTSTAMP use UTC Zulu.
    DTSTAMP is the appointment's updated_at, so it advances on every change rather than staying
    pinned to DTSTART. SEQUENCE is int(updated_at − created_at), so a later change carries a
    higher value and clients treat the re-sent invitation as an update rather than a duplicate.
    Its resolution is one second: changes landing within the same second repeat a SEQUENCE and
    a client may ignore all but the first — acceptable for human-paced edits.

    When organizer and attendee are both present the event is emitted as an iTIP invitation:
    METHOD (REQUEST for a live booking, CANCEL to withdraw it), matching STATUS, ORGANIZER, and
    ATTENDEE. With either absent it degrades to a plain event, so a dev run without a configured
    sender still produces valid output.

    SUMMARY comes from context.summary_line(), LOCATION from the service address, and
    DESCRIPTION is built from the assigned technician's name and phone (shown
    to the customer), the problem, the appointment's free-text details, and the customer phone
    line — each included when present.
    """
    start = appointment.time_range.start.astimezone(timezone.utc)
    end = appointment.time_range.end.astimezone(timezone.utc)

    def _fmt(dt) -> str:
        return dt.strftime("%Y%m%dT%H%M%SZ")

    dtstart = _fmt(start)
    dtend = _fmt(end)
    # SEQUENCE and DTSTAMP both key off updated_at, which must be non-decreasing across an
    # appointment's changes — a clock step-backward between two revisions would misorder them.
    dtstamp = _fmt(appointment.updated_at.astimezone(timezone.utc))
    sequence = int((appointment.updated_at - appointment.created_at).total_seconds())

    problem = (context.problem_description or "").strip()
    details = (appointment.details or "").strip()
    phone = (context.customer_phone or "").strip()
    address = (context.service_address or "").strip()
    technician = (context.technician_name or "").strip()
    technician_phone = (context.technician_phone or "").strip()

    description_text = "\n".join(
        part
        for part in (
            f"Technician: {technician}" if technician else "",
            f"Technician phone: {technician_phone}" if technician_phone else "",
            problem,
            details,
            f"Phone: {phone}" if phone else "",
        )
        if part
    )
    summary = _fold(f"SUMMARY:{_escape_text(context.summary_line())}")
    location_line = f"{_fold(f'LOCATION:{_escape_text(address)}')}\r\n" if address else ""
    description_line = (
        f"{_fold(f'DESCRIPTION:{_escape_text(description_text)}')}\r\n" if description_text else ""
    )

    org = (organizer or "").strip()
    att = (attendee or "").strip()
    itip = bool(org and att)
    method_line = f"METHOD:{method}\r\n" if itip else ""
    status = "CANCELLED" if method == "CANCEL" else "CONFIRMED"
    status_line = f"STATUS:{status}\r\n" if itip else ""
    organizer_line = f"{_fold(f'ORGANIZER:mailto:{org}')}\r\n" if itip else ""
    attendee_line = (
        f"{_fold('ATTENDEE;ROLE=REQ-PARTICIPANT;PARTSTAT=NEEDS-ACTION;RSVP=TRUE:mailto:' + att)}\r\n"
        if itip
        else ""
    )

    return (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//FSM//Field Service Management//EN\r\n"
        f"{method_line}"
        "BEGIN:VEVENT\r\n"
        f"UID:{uid}\r\n"
        f"DTSTAMP:{dtstamp}\r\n"
        f"DTSTART:{dtstart}\r\n"
        f"DTEND:{dtend}\r\n"
        f"SEQUENCE:{sequence}\r\n"
        f"{organizer_line}"
        f"{attendee_line}"
        f"{status_line}"
        f"{summary}\r\n"
        f"{location_line}"
        f"{description_line}"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
