"""GoogleCalendarAdapter: concrete implementation of the scheduling CalendarPort.

Targets a single configured calendar identified by calendar_id.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fsm.calendar.ports.client import GoogleCalendarClient
from fsm.scheduling.domain import build_ical_uid
from fsm.scheduling.domain.appointment import Appointment
from fsm.scheduling.domain.appointment_context import AppointmentContext
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

    def create_event(self, appointment: Appointment, context: AppointmentContext) -> str:
        body = self._build_body(appointment, context)
        body["iCalUID"] = build_ical_uid(appointment.id)
        result = self._client.import_event(self._calendar_id, body)
        return result["id"]

    def update_event(
        self,
        external_event_id: str,
        appointment: Appointment,
        context: AppointmentContext,
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
            "summary": context.summary_line(),
            "start": {"dateTime": start.isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": end.isoformat(), "timeZone": "UTC"},
        }
        address = (context.service_address or "").strip()
        if address:
            body["location"] = address
        description_parts: list[str] = []
        # The technician's event echoes the name and phone shown to the customer (grouped as one
        # block) so the technician can confirm the customer was given correct contact details.
        technician_lines = [
            f"{label}: {value.strip()}"
            for label, value in (
                ("Technician", context.technician_name),
                ("Technician phone", context.technician_phone),
            )
            if value and value.strip()
        ]
        if technician_lines:
            description_parts.append("\n".join(technician_lines))
        description_parts.extend(
            part
            for part in (context.problem_description, appointment.details)
            if part and part.strip()
        )
        phone = (context.customer_phone or "").strip()
        if phone:
            description_parts.append(f"Phone: {phone}")
        if description_parts:
            body["description"] = "\n\n".join(description_parts)
        return body
