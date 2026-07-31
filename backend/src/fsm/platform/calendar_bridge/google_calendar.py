"""GoogleCalendarAdapter: concrete implementation of the scheduling CalendarPort.

Targets a single configured calendar identified by calendar_id.
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable
from uuid import UUID

from fsm.assist.ports.chat_model import TriageSummary
from fsm.google_calendar.ports.client import GoogleCalendarClient
from fsm.platform.calendar_bridge.description_html import (
    BLOCK_SEPARATOR,
    fields_html,
    blocks_html,
    text_html,
)
from fsm.scheduling.domain import build_ical_uid
from fsm.scheduling.domain.appointment import Appointment
from fsm.scheduling.domain.appointment_context import AppointmentContext
from fsm.scheduling.domain.time_range import TimeRange


class GoogleCalendarAdapter:
    """Implements fsm.scheduling.ports.CalendarPort via the thin GoogleCalendarClient seam."""

    def __init__(
        self,
        client: GoogleCalendarClient,
        calendar_id: str,
        *,
        attendee_email: Callable[[UUID], str | None] | None = None,
        time_zone: str = "UTC",
    ) -> None:
        self._client = client
        self._calendar_id = calendar_id
        self._attendee_email = attendee_email
        # IANA zone Google renders the event in and resolves DST/recurrence against.
        self._time_zone = time_zone

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
        ical_uid = build_ical_uid(appointment.id)
        body["iCalUID"] = ical_uid
        try:
            result = self._client.insert_event(self._calendar_id, body)
            return result["id"]
        except Exception as exc:
            # Crash-retry safety: a duplicate iCalUID makes insert return 409; recover the existing
            # event id so a re-projected CREATE resolves to the same event instead of duplicating it.
            if getattr(getattr(exc, "resp", None), "status", None) == 409:
                existing = self._client.find_event_id_by_ical_uid(self._calendar_id, ical_uid)
                if existing is not None:
                    return existing
            raise

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
            "start": {"dateTime": start.isoformat(), "timeZone": self._time_zone},
            "end": {"dateTime": end.isoformat(), "timeZone": self._time_zone},
        }
        # The customer guest may move the event; the inbound reconciler validates every move
        # against the booking policy and reverts unavailable times.
        body["guestsCanModify"] = True
        address = (context.service_address or "").strip()
        if address:
            body["location"] = address
        description_parts: list[str] = []
        # The technician's event echoes the name and phone shown to the customer (grouped as one
        # block) so the technician can confirm the customer was given correct contact details.
        technician_fields = [
            (label, value.strip())
            for label, value in (
                ("Technician", context.technician_name),
                ("Technician phone", context.technician_phone),
            )
            if value and value.strip()
        ]
        if technician_fields:
            description_parts.append(fields_html(technician_fields))
        if context.triage_summary is not None:
            summary = TriageSummary.from_dict(context.triage_summary)
            description_parts.append(blocks_html(summary.blocks()))
        else:
            problem = (context.problem_description or "").strip()
            if problem:
                # A call opened from the plain description form has no structure to lay out, only
                # the customer's own words, which the event labels as the problem.
                description_parts.append(fields_html([("Problem", problem)]))
        details = (appointment.details or "").strip()
        if details:
            description_parts.append(text_html(details))
        phone = (context.customer_phone or "").strip()
        if phone:
            description_parts.append(fields_html([("Phone", phone)]))
        if description_parts:
            body["description"] = BLOCK_SEPARATOR.join(description_parts)
        if self._attendee_email is not None:
            customer_email = self._attendee_email(appointment.customer_id)
            if customer_email:
                body["attendees"] = [
                    {"email": customer_email, "responseStatus": "needsAction"}
                ]
        return body
