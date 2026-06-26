"""Inbound change DTO for the scheduling bounded context."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from fsm.scheduling.domain.time_range import TimeRange


@dataclass(frozen=True)
class InboundEventChange:
    """A normalized change observed on the technician's FSM Google calendar.

    appointment_id is parsed by the calendar adapter from the event's deterministic
    iCalUID (fsm-{appointment_id}@fsm.local). updated_at is the Google event's last
    modification time, used for last-write-wins arbitration against the DB row.
    """

    appointment_id: UUID
    cancelled: bool
    new_time_range: TimeRange | None
    details: str | None
    updated_at: datetime
