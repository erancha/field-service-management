"""Unit-of-Work port for the scheduling bounded context.

The UnitOfWork protocol groups the appointment, service-call, attachment, and
outbox repositories under a single transaction boundary. Callers work through the
context manager and call commit() to make all mutations durable; any unhandled
exception in the with-block rolls everything back automatically.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from fsm.scheduling.ports.outbox import OutboxRepository
from fsm.scheduling.ports.repositories import (
    AppointmentRepository,
    ServiceCallAttachmentRepository,
    ServiceCallRepository,
)


@runtime_checkable
class UnitOfWork(Protocol):
    """Transaction boundary encapsulating the scheduling repositories."""

    service_calls: ServiceCallRepository
    appointments: AppointmentRepository
    attachments: ServiceCallAttachmentRepository
    outbox: OutboxRepository

    def __enter__(self) -> "UnitOfWork":
        ...

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        ...

    def commit(self) -> None:
        """Flush all pending mutations and commit the current transaction."""
        ...
