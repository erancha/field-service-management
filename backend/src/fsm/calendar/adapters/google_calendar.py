"""GoogleCalendarAdapter: concrete implementation of the scheduling CalendarPort.

Targets a single configured calendar identified by calendar_id.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fsm.calendar.adapters.client import GoogleCalendarClient
from fsm.scheduling.domain.appointment import Appointment
from fsm.scheduling.domain.time_range import TimeRange


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

    def create_event(self, appointment: Appointment) -> str:
        body = self._build_body(appointment)
        body["iCalUID"] = f"fsm-{appointment.id}@fsm.local"
        result = self._client.import_event(self._calendar_id, body)
        return result["id"]

    def update_event(self, external_event_id: str, appointment: Appointment) -> None:
        body = self._build_body(appointment)
        self._client.update_event(self._calendar_id, external_event_id, body)

    def delete_event(self, external_event_id: str) -> None:
        self._client.delete_event(self._calendar_id, external_event_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_body(self, appointment: Appointment) -> dict:
        start = appointment.time_range.start
        end = appointment.time_range.end
        assert start.tzinfo is not None, (
            f"appointment.time_range.start must be tz-aware; got naive datetime {start!r}"
        )
        assert end.tzinfo is not None, (
            f"appointment.time_range.end must be tz-aware; got naive datetime {end!r}"
        )
        body: dict = {
            "summary": "Field service appointment",
            "start": {"dateTime": start.isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": end.isoformat(), "timeZone": "UTC"},
        }
        if appointment.details is not None:
            body["description"] = appointment.details
        return body
