"""Outbox port definitions for the scheduling bounded context.

The outbox allows booking use cases to enqueue calendar operations in the same
transaction as their DB writes. A separate dispatcher reads the outbox and
projects the operations to the external calendar, providing at-least-once
delivery without coupling the booking critical path to a live calendar call.

Retry policy: mark_failed increments attempts. While attempts < MAX_ATTEMPTS the
row remains PENDING so the next dispatcher run re-selects it (retryable failure).
At attempts >= MAX_ATTEMPTS the row transitions to the terminal FAILED status
(dead-letter). This gives at-most MAX_ATTEMPTS attempts before permanent failure.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable
from uuid import UUID

MAX_ATTEMPTS = 5


class OutboxOperation(str, Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"


@dataclass(frozen=True)
class OutboxEntry:
    """Immutable snapshot of a pending outbox row.

    external_event_id is only populated for DELETE entries so the dispatcher
    can call delete_event even if the appointment row has already been cleaned up.
    attempts tracks how many dispatcher runs have touched this entry.
    """

    id: UUID
    operation: OutboxOperation
    appointment_id: UUID
    external_event_id: str | None
    attempts: int


@runtime_checkable
class OutboxRepository(Protocol):
    """Persistence contract for the calendar outbox."""

    def enqueue(
        self,
        operation: OutboxOperation,
        appointment_id: UUID,
        external_event_id: str | None = None,
    ) -> None:
        """Insert a PENDING outbox row; caller owns the transaction."""
        ...

    def claim_next(self) -> OutboxEntry | None:
        """Atomically claim the oldest PENDING entry and return it, or None if the queue is empty.

        Uses SELECT … FOR UPDATE SKIP LOCKED so concurrent dispatchers never claim the same
        row: a locked row is skipped rather than blocked on, guaranteeing safe concurrency
        without serialisation stalls.
        """
        ...

    def list_pending(self, limit: int) -> list[OutboxEntry]:
        """Return up to `limit` PENDING entries ordered by creation time (FIFO)."""
        ...

    def mark_processed(self, entry_id: UUID) -> None:
        """Set the entry to PROCESSED and record the completion timestamp.

        Raises NotFoundError if entry_id is absent — a missing row after a successful claim
        is an invariant violation.
        """
        ...

    def mark_failed(self, entry_id: UUID, error: str) -> None:
        """Increment attempts and record the error.

        While attempts < MAX_ATTEMPTS the status remains PENDING so the entry is
        re-selected on the next dispatcher run (transient failure, retry).
        At attempts >= MAX_ATTEMPTS the status is set to the terminal FAILED
        (dead-letter; no further retries).

        Raises NotFoundError if entry_id is absent.
        """
        ...
