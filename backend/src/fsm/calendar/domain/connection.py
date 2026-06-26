"""CalendarConnection entity: tracks a technician's dedicated FSM calendar."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum


class CalendarConnectionStatus(str, Enum):
    """Lifecycle states for a technician's calendar connection."""

    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"


@dataclass
class CalendarConnection:
    """Mutable entity binding a technician to a provisioned FSM calendar.

    Core responsibilities:
    - Tracks which calendar (fsm_calendar_id) is assigned to a technician
    - Holds the connection lifecycle state (CONNECTED / DISCONNECTED)

    The refresh token is an infrastructure credential and is never stored on
    this entity; it lives only in the repository as an opaque encrypted blob.
    """

    technician_id: uuid.UUID
    fsm_calendar_id: str
    status: CalendarConnectionStatus

    def disconnect(self) -> None:
        """Transition the connection to DISCONNECTED."""
        self.status = CalendarConnectionStatus.DISCONNECTED
