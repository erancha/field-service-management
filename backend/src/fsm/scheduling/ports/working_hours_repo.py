"""WorkingHoursRepository port for the scheduling bounded context."""
from __future__ import annotations

from typing import Protocol
from uuid import UUID

from fsm.scheduling.domain.working_hours import WeeklyWorkingHours


class WorkingHoursRepository(Protocol):
    """Reads and writes per-technician working-hours configuration."""

    def get_for_technician(self, technician_id: UUID) -> WeeklyWorkingHours:
        """Return the stored weekly schedule, or WeeklyWorkingHours.default() when unset."""
        ...

    def set_for_technician(self, technician_id: UUID, hours: WeeklyWorkingHours) -> None:
        """Replace all working-hours rows for technician_id atomically.

        Deletes existing rows before inserting the new ones; caller commits.
        """
        ...
