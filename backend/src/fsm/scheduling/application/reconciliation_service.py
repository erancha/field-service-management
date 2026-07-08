"""Inbound reconciliation service for the scheduling bounded context.

Reconciles Google Calendar edits — by the technician on their own calendar or by the
customer guest — back into the FSM database. The DB is the merge authority: when an
inbound change conflicts with an existing active appointment or falls outside the
booking policy, the DB's version wins and a re-projection UPDATE is enqueued to push
the authoritative state back onto the calendar.

Last-write-wins (LWW) arbitration uses the Google event's last-modification timestamp
against the appointment's updated_at: a change that is not strictly newer than the
DB row is discarded without any mutation.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from uuid import UUID

from fsm.scheduling.domain.appointment import AppointmentStatus
from fsm.scheduling.domain.availability import AvailabilityInputs, is_available
from fsm.scheduling.domain.errors import NotFoundError
from fsm.scheduling.domain.time_range import TimeRange
from fsm.scheduling.ports.inbound import InboundEventChange
from fsm.scheduling.ports.notifications import NotificationPort
from fsm.scheduling.ports.outbox import OutboxOperation, OutboxRepository
from fsm.scheduling.ports.repositories import AppointmentRepository

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReconciledChange:
    """A committed inbound change whose participants' open views should refresh.

    Emitted only when the DB row actually changed (cancel, customer-decline, accepted reschedule);
    a rejected or stale edit leaves the row untouched and yields no change.
    """

    appointment_id: UUID
    customer_id: UUID
    technician_id: UUID


class ReconciliationService:
    """Applies inbound Google Calendar changes to the FSM appointment store.

    Core responsibilities:
    - LWW arbitration: discards stale inbound edits based on updated_at comparison
    - Booking-policy guard: an inbound time-move outside working hours, on an excluded day, or
      double-booking is reverted (re-projection UPDATE) and reported via
      appointment_reschedule_rejected
    - Customer decline: cancels the appointment, removes the calendar event, and notifies both
      parties
    - Routes cancel/reschedule/no-op paths to the correct domain mutation and notification;
      description-only inbound edits are ignored (the description is a rendered projection)
    """

    def __init__(
        self,
        appointments: AppointmentRepository,
        outbox: OutboxRepository,
        notifications: NotificationPort,
        *,
        availability_inputs: Callable[[UUID, datetime], AvailabilityInputs],
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._appointments = appointments
        self._outbox = outbox
        self._notifications = notifications
        self._availability_inputs = availability_inputs
        self._clock = clock

    def reconcile(self, change: InboundEventChange) -> ReconciledChange | None:
        """Apply an inbound calendar change to the DB; returns the committed change, or None."""
        try:
            appt = self._appointments.get(change.appointment_id)
        except NotFoundError:
            _log.info(
                "inbound change for unknown appointment %s — discarding",
                change.appointment_id,
            )
            return None

        # Last-write-wins: ignore an inbound edit that is not strictly newer than the DB row.
        if change.updated_at <= appt.updated_at:
            return None

        if appt.status is AppointmentStatus.CANCELLED:
            return None

        if change.cancelled:
            appt.cancel(now=self._clock())
            self._appointments.save(appt)
            self._notifications.appointment_cancelled(appt)
            return self._change_for(appt)

        if change.customer_declined:
            # The declined event still exists on the technician's calendar (only the RSVP
            # changed), so removing it needs an explicit DELETE, unlike the cancelled branch.
            appt.cancel(now=self._clock())
            self._appointments.save(appt)
            self._outbox.enqueue(
                OutboxOperation.DELETE, appt.id, external_event_id=appt.external_event_id
            )
            self._notifications.appointment_cancelled(appt)
            return self._change_for(appt)

        if change.new_time_range is not None and change.new_time_range != appt.time_range:
            if not self._accepts(appt, change.new_time_range):
                # DB wins: re-project the authoritative time back onto the Google event and
                # tell both parties why the move did not stick.
                self._outbox.enqueue(OutboxOperation.UPDATE, appt.id)
                self._notifications.appointment_reschedule_rejected(appt)
                return None

            appt.reschedule(change.new_time_range, now=self._clock())
            self._appointments.save(appt)
            self._notifications.appointment_rescheduled(appt)
            return self._change_for(appt)

        # No time or cancellation change: a description-only edit or a projection echo of our
        # own outbound update. The event description is a rendered composition (problem +
        # details + phone), not the raw details field, so reflecting it back would overwrite
        # appt.details with the whole body and compound on every re-projection. Left as a no-op.
        return None

    @staticmethod
    def _change_for(appt) -> ReconciledChange:
        return ReconciledChange(
            appointment_id=appt.id,
            customer_id=appt.customer_id,
            technician_id=appt.technician_id,
        )

    def _accepts(self, appt, new_time_range: TimeRange) -> bool:
        """True iff the proposed time satisfies the full booking policy for this technician."""
        inputs = self._availability_inputs(appt.technician_id, new_time_range.start)
        if not is_available(
            working_hours=inputs.working_hours,
            tz=inputs.tz,
            excluded_dates=inputs.excluded_dates,
            time_range=new_time_range,
        ):
            _log.warning(
                "inbound reschedule for appointment %s falls outside the booking policy",
                appt.id,
            )
            return False
        for existing in self._appointments.list_for_technician_between(
            appt.technician_id, new_time_range.start, new_time_range.end
        ):
            if existing.id == appt.id:
                continue
            if existing.time_range.overlaps(new_time_range):
                _log.warning(
                    "inbound reschedule for appointment %s conflicts with appointment %s",
                    appt.id,
                    existing.id,
                )
                return False
        return True
