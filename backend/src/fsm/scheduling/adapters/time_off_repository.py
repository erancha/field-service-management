"""SQLAlchemy adapter for the TimeOffRepository port."""
from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from fsm.scheduling.adapters.orm import TimeOffRow


class SqlAlchemyTimeOffRepository:
    """Session-scoped adapter; caller controls transaction lifecycle."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, technician_id: UUID, off_date: date) -> None:
        """Mark off_date as a day off for technician_id; idempotent on duplicate."""
        stmt = (
            insert(TimeOffRow)
            .values(technician_id=technician_id, off_date=off_date)
            .on_conflict_do_nothing(index_elements=["technician_id", "off_date"])
        )
        self._session.execute(stmt)
        self._session.flush()

    def remove(self, technician_id: UUID, off_date: date) -> None:
        """Unmark off_date as a day off; no-op if the row does not exist."""
        self._session.query(TimeOffRow).filter(
            TimeOffRow.technician_id == technician_id,
            TimeOffRow.off_date == off_date,
        ).delete(synchronize_session=False)
        self._session.flush()

    def list_between(self, technician_id: UUID, start: date, end: date) -> set[date]:
        """Return day-off dates for technician_id in [start, end] inclusive."""
        rows = (
            self._session.query(TimeOffRow)
            .filter(
                TimeOffRow.technician_id == technician_id,
                TimeOffRow.off_date >= start,
                TimeOffRow.off_date <= end,
            )
            .all()
        )
        return {row.off_date for row in rows}
