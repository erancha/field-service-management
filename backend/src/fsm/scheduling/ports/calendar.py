"""Calendar port definition for the scheduling bounded context.

Defines the outbound interface for reading technician availability and managing
calendar events in an external calendar system (e.g. Google Calendar). The domain
layer depends only on this protocol; adapters supply the concrete implementation.
"""
from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from fsm.scheduling.domain.appointment import Appointment
from fsm.scheduling.domain.time_range import TimeRange


@runtime_checkable
class CalendarPort(Protocol):
    """Outbound interface for an external calendar system."""

    def get_busy(
        self,
        technician_id: UUID,
        start: datetime,
        end: datetime,
    ) -> list[TimeRange]:
        """Return opaque busy intervals for a technician within [start, end).

        Each TimeRange represents a window during which the technician is
        unavailable according to the external calendar.
        """
        ...

    def create_event(self, appointment: Appointment) -> str:
        """Create a calendar event for the appointment and return the external event id."""
        ...

    def update_event(self, external_event_id: str, appointment: Appointment) -> None:
        """Update the calendar event identified by external_event_id to reflect the appointment."""
        ...

    def delete_event(self, external_event_id: str) -> None:
        """Remove the calendar event identified by external_event_id."""
        ...
