"""Appointment entity linking a service call to a technician at a scheduled time."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from fsm.scheduling.domain.errors import InvalidTransition
from fsm.scheduling.domain.time_range import TimeRange


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RESCHEDULED = "RESCHEDULED"
    CANCELLED = "CANCELLED"


class AuditAction(str, Enum):
    BOOKED = "BOOKED"
    RESCHEDULED = "RESCHEDULED"
    CANCELLED = "CANCELLED"
    DETAILS_ADDED = "DETAILS_ADDED"


_TERMINAL_STATES = frozenset({AppointmentStatus.CANCELLED})


@dataclass(frozen=True)
class AuditRecord:
    """Immutable record of a single lifecycle transition, pending repository drain."""

    action: AuditAction
    occurred_at: datetime


@dataclass
class Appointment:
    """Mutable entity representing a confirmed visit by a technician to a customer.

    CANCELLED is a terminal state: reschedule, cancel, and add_details all raise
    InvalidTransition once an appointment is cancelled.

    Lifecycle:
      SCHEDULED → RESCHEDULED (via reschedule)
      RESCHEDULED → RESCHEDULED (multiple reschedules allowed)
      SCHEDULED | RESCHEDULED → CANCELLED (via cancel)

    Mutation methods accept an explicit `now` datetime from the caller so that
    updated_at is deterministic and testable.

    pending_audits accumulates AuditRecord entries on each mutation. The repository
    drains this list via drain_audits() when persisting, writing one audit row per
    record in the same transaction as the appointment row. The field is excluded from
    equality and repr because pending audits are incidental bookkeeping, not part of the
    appointment's identity.
    """

    id: uuid.UUID
    service_call_id: uuid.UUID
    technician_id: uuid.UUID
    customer_id: uuid.UUID
    time_range: TimeRange
    status: AppointmentStatus
    details: str | None
    created_at: datetime
    updated_at: datetime
    external_event_id: str | None = None
    pending_audits: list[AuditRecord] = field(default_factory=list, compare=False, repr=False)

    def _guard_not_cancelled(self, operation: str) -> None:
        if self.status in _TERMINAL_STATES:
            raise InvalidTransition(
                f"Cannot {operation} a {self.status.value!r} appointment; "
                "CANCELLED is a terminal state."
            )

    def _touch(self, now: datetime) -> None:
        self.updated_at = now

    def _append_audit(self, action: AuditAction, now: datetime) -> None:
        self.pending_audits.append(AuditRecord(action=action, occurred_at=now))

    def record_booked(self, now: datetime) -> None:
        """Record a BOOKED audit event for a freshly constructed appointment."""
        self._append_audit(AuditAction.BOOKED, now)

    def drain_audits(self) -> list[AuditRecord]:
        """Return all pending audit records and clear the list.

        The repository calls this immediately after flushing the appointment row,
        so audits are written in the same transaction as the entity change.
        """
        records, self.pending_audits = self.pending_audits, []
        return records

    def assign_external_event(self, event_id: str) -> None:
        """Store the opaque id of the calendar event created for this appointment."""
        self.external_event_id = event_id

    def reschedule(self, new_range: TimeRange, *, now: datetime) -> None:
        """Replace the scheduled time window and move status to RESCHEDULED."""
        self._guard_not_cancelled("reschedule")
        self.time_range = new_range
        self.status = AppointmentStatus.RESCHEDULED
        self._touch(now)
        self._append_audit(AuditAction.RESCHEDULED, now)

    def cancel(self, *, now: datetime) -> None:
        """Mark the appointment as CANCELLED (terminal)."""
        self._guard_not_cancelled("cancel")
        self.status = AppointmentStatus.CANCELLED
        self._touch(now)
        self._append_audit(AuditAction.CANCELLED, now)

    def add_details(self, text: str, *, now: datetime) -> None:
        """Attach or replace free-text details on the appointment."""
        self._guard_not_cancelled("add details to")
        self.details = text
        self._touch(now)
        self._append_audit(AuditAction.DETAILS_ADDED, now)
