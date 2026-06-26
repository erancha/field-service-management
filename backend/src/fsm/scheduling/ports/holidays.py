"""HolidayRepository port for the scheduling bounded context."""
from __future__ import annotations

from datetime import date
from typing import Iterable, Protocol

from fsm.scheduling.domain.holiday import Holiday


class HolidayRepository(Protocol):
    """Reads and writes the local holiday cache."""

    def list_between(self, start: date, end: date) -> set[date]:
        """Return holiday dates in [start, end] inclusive."""
        ...

    def upsert_many(self, holidays: Iterable[Holiday]) -> None:
        """Insert or update holidays by date; idempotent."""
        ...
