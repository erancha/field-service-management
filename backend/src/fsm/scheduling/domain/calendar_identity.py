"""Identity scheme linking an appointment to its calendar event (fsm-{appointment_id}@fsm.local).

This iCalUID is the identity key of the two-way calendar sync: the Google Calendar projection
stamps the event with it on insert, and inbound reconciliation recognizes FSM-owned events by
parsing it back. Every producer and consumer of the scheme must go through
this module — a format drift between sites breaks dispatch dedupe and inbound reconciliation
silently, because foreign-looking events are discarded by design.
"""
from __future__ import annotations

import re
from uuid import UUID

_ICAL_UID_RE = re.compile(
    r"^fsm-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})@fsm\.local$",
    re.IGNORECASE,
)


def build_ical_uid(appointment_id: UUID) -> str:
    """Return the deterministic iCalUID identifying the appointment's calendar event."""
    return f"fsm-{appointment_id}@fsm.local"


def parse_ical_uid(value: str) -> UUID | None:
    """Return the appointment UUID encoded in an iCalUID, or None for a foreign event.

    None is a legal domain state: calendars carry events FSM does not own, and consumers
    discard those by design.
    """
    match = _ICAL_UID_RE.match(value)
    if match is None:
        return None
    return UUID(match.group(1))
