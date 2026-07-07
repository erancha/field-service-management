"""SQLAlchemy adapter for the WorkingHoursRepository port."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from fsm.scheduling.adapters.orm import WorkingHoursRow
from fsm.scheduling.domain.working_hours import DailyHours, WeeklyWorkingHours


class SqlAlchemyWorkingHoursRepository:
    """Session-scoped adapter; caller controls transaction lifecycle."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_for_technician(self, technician_id: UUID) -> WeeklyWorkingHours:
        """Return the stored weekly schedule, or WeeklyWorkingHours.default() when unset."""
        rows = (
            self._session.query(WorkingHoursRow)
            .filter(WorkingHoursRow.technician_id == technician_id)
            .all()
        )
        if not rows:
            return WeeklyWorkingHours.default()
        windows = tuple(
            DailyHours(weekday=row.weekday, start=row.start_time, end=row.end_time)
            for row in rows
        )
        return WeeklyWorkingHours(windows=windows)

    def set_for_technician(self, technician_id: UUID, hours: WeeklyWorkingHours) -> None:
        """Replace all working-hours rows for technician_id atomically.

        Deletes existing rows for the technician then inserts the new ones in the
        same transaction; caller commits.
        """
        self._session.query(WorkingHoursRow).filter(
            WorkingHoursRow.technician_id == technician_id
        ).delete(synchronize_session=False)

        for dh in hours.windows:
            self._session.add(
                WorkingHoursRow(
                    technician_id=technician_id,
                    weekday=dh.weekday,
                    start_time=dh.start,
                    end_time=dh.end,
                )
            )
        self._session.flush()
