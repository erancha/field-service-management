"""SQLAlchemy repository adapter for the calendar bounded context.

Wraps a SQLAlchemy Session and maps between CalendarConnectionRow and the
CalendarConnection domain entity. The session's transaction lifecycle is
controlled by the caller; this adapter only flushes, never commits.
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from fsm.google_calendar.adapters.orm import CalendarConnectionRow
from fsm.google_calendar.domain.connection import CalendarConnection, CalendarConnectionStatus
from fsm.google_calendar.domain.errors import DuplicateTechnicianError, NotFoundError

_log = logging.getLogger(__name__)

_UNIQUE_TECHNICIAN_CONSTRAINT = "calendar_connection_pkey"


def _translate_integrity_error(exc: IntegrityError) -> None:
    """Re-raise exc as DuplicateTechnicianError when it originates from the PK constraint.

    Inspects the psycopg diagnostic constraint_name first; falls back to a
    substring check on the stringified original error for other drivers.
    For any other IntegrityError the original exception propagates unchanged.
    """
    constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
    if constraint is None:
        raw = str(exc.orig)
        if _UNIQUE_TECHNICIAN_CONSTRAINT in raw:
            constraint = _UNIQUE_TECHNICIAN_CONSTRAINT
    if constraint == _UNIQUE_TECHNICIAN_CONSTRAINT:
        _log.warning("Duplicate technician constraint fired; translating to DuplicateTechnicianError")
        raise DuplicateTechnicianError(
            "A calendar connection for this technician already exists"
        ) from exc
    raise exc


def _row_to_connection(row: CalendarConnectionRow) -> CalendarConnection:
    return CalendarConnection(
        technician_id=row.technician_id,
        fsm_calendar_id=row.fsm_calendar_id,
        status=CalendarConnectionStatus(row.status),
    )


class SqlAlchemyCalendarConnectionRepository:
    """Session-scoped SQLAlchemy adapter for CalendarConnection persistence."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, connection: CalendarConnection, encrypted_refresh_token: str) -> None:
        """Insert a new connection row with its encrypted token.

        Translates a duplicate-technician IntegrityError to DuplicateTechnicianError.
        """
        row = CalendarConnectionRow(
            technician_id=connection.technician_id,
            fsm_calendar_id=connection.fsm_calendar_id,
            encrypted_refresh_token=encrypted_refresh_token,
            status=connection.status.value,
        )
        self._session.add(row)
        try:
            self._session.flush()
        except IntegrityError as exc:
            _translate_integrity_error(exc)

    def get(self, technician_id: uuid.UUID) -> CalendarConnection:
        """Return the connection for the given technician.

        Raises NotFoundError if absent.
        """
        row = self._session.get(CalendarConnectionRow, technician_id)
        if row is None:
            raise NotFoundError(f"CalendarConnection for technician {technician_id!r} not found")
        return _row_to_connection(row)

    def get_encrypted_token(self, technician_id: uuid.UUID) -> str:
        """Return the encrypted token blob for the given technician.

        Raises NotFoundError if absent.
        """
        row = self._session.get(CalendarConnectionRow, technician_id)
        if row is None:
            raise NotFoundError(f"No encrypted token for technician {technician_id!r}")
        return row.encrypted_refresh_token

    def save(self, connection: CalendarConnection) -> None:
        """Persist mutations to an already-stored connection."""
        row = self._session.get(CalendarConnectionRow, connection.technician_id)
        if row is None:
            raise NotFoundError(f"CalendarConnection for technician {connection.technician_id!r} not found")
        row.fsm_calendar_id = connection.fsm_calendar_id
        row.status = connection.status.value
        self._session.flush()

    def reconnect(self, technician_id: uuid.UUID, encrypted_refresh_token: str) -> None:
        """Replace the stored token and set status to CONNECTED, reusing the existing calendar.

        Raises NotFoundError if the connection row is absent.
        """
        row = self._session.get(CalendarConnectionRow, technician_id)
        if row is None:
            raise NotFoundError(f"CalendarConnection for technician {technician_id!r} not found")
        row.encrypted_refresh_token = encrypted_refresh_token
        row.status = CalendarConnectionStatus.CONNECTED.value
        self._session.flush()

    def reprovision(
        self, technician_id: uuid.UUID, new_calendar_id: str, encrypted_refresh_token: str
    ) -> None:
        """Repoint the connection at a new calendar and return it to CONNECTED.

        Replaces the calendar id, token, and status together, and drops the sync token so the next
        inbound sync runs a full listing against the fresh calendar. Raises NotFoundError if the
        connection row is absent.
        """
        row = self._session.get(CalendarConnectionRow, technician_id)
        if row is None:
            raise NotFoundError(f"CalendarConnection for technician {technician_id!r} not found")
        row.fsm_calendar_id = new_calendar_id
        row.encrypted_refresh_token = encrypted_refresh_token
        row.status = CalendarConnectionStatus.CONNECTED.value
        row.sync_token = None
        self._session.flush()

    def get_sync_token(self, technician_id: uuid.UUID) -> str | None:
        """Return the stored Google Calendar sync token for the given technician.

        Raises NotFoundError if the connection row is absent.
        """
        row = self._session.get(CalendarConnectionRow, technician_id)
        if row is None:
            raise NotFoundError(f"CalendarConnection for technician {technician_id!r} not found")
        return row.sync_token

    def set_sync_token(self, technician_id: uuid.UUID, token: str | None) -> None:
        """Persist an updated sync token for the given technician.

        Raises NotFoundError if the connection row is absent.
        """
        row = self._session.get(CalendarConnectionRow, technician_id)
        if row is None:
            raise NotFoundError(f"CalendarConnection for technician {technician_id!r} not found")
        row.sync_token = token
        self._session.flush()

    def list_connected(self) -> list[CalendarConnection]:
        """Return all connections whose status is CONNECTED.

        Used by the inbound poller to enumerate technicians requiring sync.
        """
        rows = self._session.scalars(
            select(CalendarConnectionRow).where(
                CalendarConnectionRow.status == CalendarConnectionStatus.CONNECTED.value
            )
        ).all()
        return [_row_to_connection(row) for row in rows]
