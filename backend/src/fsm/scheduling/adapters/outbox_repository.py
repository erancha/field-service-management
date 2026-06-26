"""SQLAlchemy outbox repository adapter for the scheduling bounded context.

Implements OutboxRepository against the calendar_outbox table. The session
lifecycle is controlled by the caller (SqlAlchemyUnitOfWork); this adapter
only flushes, never commits.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from fsm.scheduling.adapters.orm import OutboxRow
from fsm.scheduling.domain.errors import NotFoundError
from fsm.scheduling.ports.outbox import MAX_ATTEMPTS, OutboxEntry, OutboxOperation


class SqlAlchemyOutboxRepository:
    """Session-scoped SQLAlchemy adapter for calendar outbox persistence."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def enqueue(
        self,
        operation: OutboxOperation,
        appointment_id: uuid.UUID,
        external_event_id: str | None = None,
    ) -> None:
        """Insert a PENDING outbox row; caller owns the transaction."""
        row = OutboxRow(
            id=uuid.uuid4(),
            operation=operation.value,
            appointment_id=appointment_id,
            external_event_id=external_event_id,
            status="PENDING",
            attempts=0,
        )
        self._session.add(row)
        self._session.flush()

    def claim_next(self) -> OutboxEntry | None:
        """Atomically claim the oldest PENDING entry and return it, or None if empty.

        Uses SELECT … FOR UPDATE SKIP LOCKED so concurrent dispatchers skip rows
        already held by another transaction, guaranteeing each entry is processed
        by exactly one dispatcher at a time.
        """
        row = (
            self._session.query(OutboxRow)
            .filter(OutboxRow.status == "PENDING")
            .order_by(OutboxRow.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
            .first()
        )
        if row is None:
            return None
        return OutboxEntry(
            id=row.id,
            operation=OutboxOperation(row.operation),
            appointment_id=row.appointment_id,
            external_event_id=row.external_event_id,
            attempts=row.attempts,
        )

    def list_pending(self, limit: int) -> list[OutboxEntry]:
        """Return up to `limit` PENDING entries ordered by creation time (FIFO)."""
        rows = (
            self._session.query(OutboxRow)
            .filter(OutboxRow.status == "PENDING")
            .order_by(OutboxRow.created_at.asc())
            .limit(limit)
            .all()
        )
        return [
            OutboxEntry(
                id=row.id,
                operation=OutboxOperation(row.operation),
                appointment_id=row.appointment_id,
                external_event_id=row.external_event_id,
                attempts=row.attempts,
            )
            for row in rows
        ]

    def mark_processed(self, entry_id: uuid.UUID) -> None:
        """Set the entry to PROCESSED and record the completion timestamp.

        Raises NotFoundError if entry_id is absent.
        """
        row = self._session.get(OutboxRow, entry_id)
        if row is None:
            raise NotFoundError(f"OutboxEntry {entry_id!r} not found")
        row.status = "PROCESSED"
        row.processed_at = datetime.now(timezone.utc)
        self._session.flush()

    def mark_failed(self, entry_id: uuid.UUID, error: str) -> None:
        """Increment attempts and record the error.

        While attempts < MAX_ATTEMPTS the status remains PENDING (retryable).
        At attempts >= MAX_ATTEMPTS the status is set to terminal FAILED (dead-letter).

        Raises NotFoundError if entry_id is absent.
        """
        row = self._session.get(OutboxRow, entry_id)
        if row is None:
            raise NotFoundError(f"OutboxEntry {entry_id!r} not found")
        row.attempts += 1
        row.last_error = error
        if row.attempts >= MAX_ATTEMPTS:
            row.status = "FAILED"
        self._session.flush()
