"""Adapter that maps raw Google Calendar change events to InboundEventChange DTOs.

Filters out events that do not belong to FSM (non-matching or absent iCalUID) so
downstream reconciliation only sees changes that are owned by this system.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from fsm.google_calendar.ports.client import GoogleCalendarClient
from fsm.scheduling.domain import parse_ical_uid
from fsm.scheduling.domain.time_range import TimeRange
from fsm.scheduling.ports.inbound import InboundEventChange

_log = logging.getLogger(__name__)


def _parse_utc(value: str) -> datetime:
    """Parse an ISO-8601 / RFC-3339 datetime string and return an aware UTC datetime.

    Handles the trailing-Z variant that Python < 3.11 does not parse directly.
    """
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized).astimezone(timezone.utc)


def _extract_appointment_id(raw_event: dict) -> UUID | None:
    """Return the appointment UUID from the event's iCalUID, or None if it does not match."""
    ical_uid = raw_event.get("iCalUID")
    if not ical_uid:
        return None
    return parse_ical_uid(ical_uid)


def _map_event(raw_event: dict) -> InboundEventChange | None:
    """Convert a raw Google Calendar event dict to an InboundEventChange.

    Returns None for events with missing or non-FSM iCalUIDs.
    """
    appointment_id = _extract_appointment_id(raw_event)
    if appointment_id is None:
        return None

    cancelled = raw_event.get("status") == "cancelled"

    new_time_range: TimeRange | None = None
    start_dt_str = raw_event.get("start", {}).get("dateTime")
    end_dt_str = raw_event.get("end", {}).get("dateTime")
    if start_dt_str and end_dt_str:
        new_time_range = TimeRange(
            start=_parse_utc(start_dt_str),
            end=_parse_utc(end_dt_str),
        )

    # The attendees key is absent on events projected without a guest (bare contexts,
    # events predating the guest model) — a legal state that simply means no RSVP exists.
    customer_declined = any(
        attendee.get("responseStatus") == "declined"
        for attendee in raw_event.get("attendees", ())
    )

    return InboundEventChange(
        appointment_id=appointment_id,
        cancelled=cancelled,
        new_time_range=new_time_range,
        updated_at=_parse_utc(raw_event["updated"]),
        customer_declined=customer_declined,
    )


class GoogleCalendarSyncAdapter:
    """Maps a stream of raw Google Calendar change events to InboundEventChange DTOs.

    Core responsibilities:
    - Delegates the actual API call to the injected GoogleCalendarClient
    - Filters out non-FSM events based on iCalUID pattern matching
    - Normalizes datetimes to UTC and builds typed InboundEventChange instances
    """

    def __init__(self, client: GoogleCalendarClient, calendar_id: str) -> None:
        self._client = client
        self._calendar_id = calendar_id

    def list_changes(
        self, sync_token: str | None
    ) -> tuple[list[InboundEventChange], str]:
        """Return FSM-owned changes since sync_token and the next sync token.

        Foreign or malformed events (unrecognized iCalUID) are silently discarded.
        """
        raw_events, next_sync_token = self._client.list_changes(
            self._calendar_id, sync_token
        )
        changes: list[InboundEventChange] = []
        for raw_event in raw_events:
            change = _map_event(raw_event)
            if change is not None:
                changes.append(change)
        return changes, next_sync_token
