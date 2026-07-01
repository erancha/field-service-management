"""GoogleCalendarAdapter: concrete implementation of the scheduling CalendarPort.

Targets a single configured calendar identified by calendar_id.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fsm.calendar.adapters.client import GoogleCalendarClient
from fsm.scheduling.domain.appointment import Appointment
from fsm.scheduling.domain.appointment_context import AppointmentContext
from fsm.scheduling.domain.time_range import TimeRange

_TITLE_PROBLEM_LIMIT = 60


def _summarize_problem(text: str) -> str:
    """Return the first line of text, truncated to the title limit with an ellipsis when longer."""
    stripped = text.strip()
    if not stripped:
        return ""
    first_line = stripped.splitlines()[0]
    if len(first_line) <= _TITLE_PROBLEM_LIMIT:
        return first_line
    return first_line[: _TITLE_PROBLEM_LIMIT - 1].rstrip() + "…"


def _summary(context: AppointmentContext) -> str:
    """Compose the event title from whatever context is available.

    Falls back to a generic title when neither customer name nor problem is known.
    """
    name = (context.customer_name or "").strip()
    problem = _summarize_problem(context.problem_description or "")
    if name and problem:
        return f"{name} — {problem}"
    if name:
        return name
    if problem:
        return problem
    return "Field service appointment"


class GoogleCalendarAdapter:
    """Implements fsm.scheduling.ports.CalendarPort via the thin GoogleCalendarClient seam."""

    def __init__(self, client: GoogleCalendarClient, calendar_id: str) -> None:
        self._client = client
        self._calendar_id = calendar_id

    # ------------------------------------------------------------------
    # CalendarPort
    # ------------------------------------------------------------------

    def get_busy(
        self,
        technician_id: UUID,
        start: datetime,
        end: datetime,
    ) -> list[TimeRange]:
        intervals = self._client.query_busy(self._calendar_id, start, end)
        return [TimeRange(s, e) for s, e in intervals]

    def create_event(
        self, appointment: Appointment, context: AppointmentContext = AppointmentContext()
    ) -> str:
        body = self._build_body(appointment, context)
        body["iCalUID"] = f"fsm-{appointment.id}@fsm.local"
        result = self._client.import_event(self._calendar_id, body)
        return result["id"]

    def update_event(
        self,
        external_event_id: str,
        appointment: Appointment,
        context: AppointmentContext = AppointmentContext(),
    ) -> None:
        body = self._build_body(appointment, context)
        self._client.update_event(self._calendar_id, external_event_id, body)

    def delete_event(self, external_event_id: str) -> None:
        self._client.delete_event(self._calendar_id, external_event_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_body(self, appointment: Appointment, context: AppointmentContext) -> dict:
        start = appointment.time_range.start
        end = appointment.time_range.end
        assert start.tzinfo is not None, (
            f"appointment.time_range.start must be tz-aware; got naive datetime {start!r}"
        )
        assert end.tzinfo is not None, (
            f"appointment.time_range.end must be tz-aware; got naive datetime {end!r}"
        )
        body: dict = {
            "summary": _summary(context),
            "start": {"dateTime": start.isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": end.isoformat(), "timeZone": "UTC"},
        }
        description_parts = [
            part for part in (context.problem_description, appointment.details) if part
        ]
        if description_parts:
            body["description"] = "\n\n".join(description_parts)
        return body
