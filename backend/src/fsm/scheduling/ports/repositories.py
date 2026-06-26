"""Repository port definitions for the scheduling bounded context.

These protocols define the persistence boundary: how service calls and
appointments are stored and retrieved. Concrete adapters (SQL, in-memory)
implement these without the domain layer depending on them.
"""
from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from fsm.scheduling.domain.appointment import Appointment
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
