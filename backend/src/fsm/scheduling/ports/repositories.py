"""Repository port definitions for the scheduling bounded context.

These protocols define the persistence boundary: how service calls and
appointments are stored and retrieved. Concrete adapters (SQL, in-memory)
implement these without the domain layer depending on them.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from fsm.scheduling.domain.appointment import Appointment
from fsm.scheduling.domain.attachment import ServiceCallAttachment
from fsm.scheduling.domain.service_call import ServiceCall


@runtime_checkable
class ServiceCallRepository(Protocol):
    """Persistence contract for ServiceCall entities."""

    def add(self, service_call: ServiceCall) -> None:
        """Persist a new service call; caller ensures the id is unique."""
        ...

    def get(self, service_call_id: UUID) -> ServiceCall:
        """Return the service call with the given id.

        Raises NotFoundError if no such service call exists.
        """
        ...

    def save(self, service_call: ServiceCall) -> None:
        """Persist mutations to an already-stored service call."""
        ...

    def remove(self, service_call_id: UUID) -> None:
        """Delete the service call. Raises NotFoundError if no such service call exists."""
        ...


@runtime_checkable
class AppointmentRepository(Protocol):
    """Persistence contract for Appointment entities."""

    def add(self, appointment: Appointment) -> None:
        """Persist a new appointment; caller ensures the id is unique."""
        ...

    def get(self, appointment_id: UUID) -> Appointment:
        """Return the appointment with the given id.

        Raises NotFoundError if no such appointment exists.
        """
        ...

    def save(self, appointment: Appointment) -> None:
        """Persist mutations to an already-stored appointment."""
        ...

    def list_for_technician_between(
        self,
        technician_id: UUID,
        start: datetime,
        end: datetime,
    ) -> list[Appointment]:
        """Return active appointments for a technician that overlap [start, end).

        Half-open boundary contract (matches the SQL EXCLUDE constraint):
        - An appointment ending EXACTLY at `start` is EXCLUDED (no overlap).
        - An appointment starting EXACTLY at `end` is EXCLUDED (no overlap).
        - An appointment that overlaps by any positive duration is INCLUDED.

        Excludes CANCELLED appointments.
        """
        ...

    def list_upcoming_for_technician(
        self, technician_id: UUID, now: datetime, limit: int
    ) -> list[Appointment]:
        """Return this technician's soonest not-yet-ended, non-cancelled appointments.

        Ordered by (start, id); at most `limit` rows. An appointment already in progress
        (start <= now < end) is still upcoming.
        """
        ...

    def list_upcoming_for_customer(
        self, customer_id: UUID, now: datetime, limit: int
    ) -> list[Appointment]:
        """Return this customer's soonest not-yet-ended, non-cancelled appointments (see above)."""
        ...

    def list_upcoming_all(self, now: datetime, limit: int) -> list[Appointment]:
        """Return the soonest not-yet-ended, non-cancelled appointments across all technicians."""
        ...

    def list_for_service_call(self, service_call_id: UUID) -> list[Appointment]:
        """Return every appointment booked against this service call."""
        ...

    def list_customer_cancellations_since(self, customer_id: UUID, since: datetime) -> list[datetime]:
        """Return when each of this customer's appointments was cancelled, at or after `since`.

        Sourced from the append-only audit log's CANCELLED records, so cancellations keep
        counting toward the booking rate limit even though the appointments are terminal.
        """
        ...


@runtime_checkable
class ServiceCallAttachmentRepository(Protocol):
    """Persistence contract for photos a service call inherited from its triage conversation."""

    def add_all(self, attachments: Sequence[ServiceCallAttachment]) -> None:
        """Persist new attachment rows; caller ensures uniqueness of each id."""
        ...

    def get(self, attachment_id: UUID) -> ServiceCallAttachment:
        """Return the attachment with the given id.

        Raises NotFoundError if no such attachment exists.
        """
        ...

    def list_for_service_call(self, service_call_id: UUID) -> list[ServiceCallAttachment]:
        """Return every attachment carried by this service call, oldest first."""
        ...
