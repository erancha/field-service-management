"""TimeOffRepository port for the scheduling bounded context."""
from __future__ import annotations

from datetime import date
from typing import Protocol
from uuid import UUID


class TimeOffRepository(Protocol):
    """Reads and writes per-technician day-off records."""

    def add(self, technician_id: UUID, off_date: date) -> None:
        """Mark off_date as a day off for technician_id; idempotent."""
        ...

    def remove(self, technician_id: UUID, off_date: date) -> None:
        """Unmark off_date as a day off for technician_id; no-op if absent."""
        ...

    def list_between(self, technician_id: UUID, start: date, end: date) -> set[date]:
        """Return day-off dates for technician_id in [start, end] inclusive."""
        ...
