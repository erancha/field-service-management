"""SQLAlchemy adapter for the HolidayRepository port."""
from __future__ import annotations

from datetime import date
from typing import Iterable

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from fsm.scheduling.adapters.orm import HolidayRow
from fsm.scheduling.domain.holiday import Holiday


class SqlAlchemyHolidayRepository:
    """Session-scoped adapter; caller controls transaction lifecycle."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_between(self, start: date, end: date) -> set[date]:
        """Return holiday dates in [start, end] inclusive."""
        rows = (
            self._session.query(HolidayRow)
            .filter(HolidayRow.holiday_date >= start, HolidayRow.holiday_date <= end)
            .all()
        )
        return {row.holiday_date for row in rows}

    def upsert_many(self, holidays: Iterable[Holiday]) -> None:
        """Insert or replace holidays by date; no-op on empty input."""
        items = list(holidays)
        if not items:
            return
        stmt = insert(HolidayRow).values(
            [{"holiday_date": h.date, "name": h.name} for h in items]
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["holiday_date"],
            set_={"name": stmt.excluded.name},
        )
        self._session.execute(stmt)
        self._session.flush()
