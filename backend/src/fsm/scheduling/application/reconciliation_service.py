"""Inbound reconciliation service for the scheduling bounded context.

Reconciles technician-initiated Google Calendar edits back into the FSM database.
The DB is the merge authority: when an inbound change conflicts with an existing
active appointment, the DB's version wins and a re-projection UPDATE is enqueued to
push the authoritative state back onto the calendar.

Last-write-wins (LWW) arbitration uses the Google event's last-modification timestamp
against the appointment's updated_at: a change that is not strictly newer than the
DB row is discarded without any mutation.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable

from fsm.scheduling.domain.appointment import AppointmentStatus
from fsm.scheduling.domain.errors import NotFoundError, SlotUnavailable
from fsm.scheduling.ports.inbound import InboundEventChange
from fsm.scheduling.ports.notifications import NotificationPort
from fsm.scheduling.ports.outbox import OutboxOperation, OutboxRepository
from fsm.scheduling.ports.repositories import AppointmentRepository

_log = logging.getLogger(__name__)


class ReconciliationService:
    """Applies inbound Google Calendar changes to the FSM appointment store.

    Core responsibilities:
    - LWW arbitration: discards stale inbound edits based on updated_at comparison
    - DB-authority overlap guard: re-projects the DB's time when a Google edit would
      create a double-booking
    - Routes cancel/reschedule/content-edit/no-op paths to the correct domain mutation
      and notification
    """

    def __init__(
        self,
        appointments: AppointmentRepository,
        outbox: OutboxRepository,
        notifications: NotificationPort,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._appointments = appointments
        self._outbox = outbox
        self._notifications = notifications
        self._clock = clock

    def reconcile(self, change: InboundEventChange) -> None:
        """Apply a single inbound calendar change to the DB, respecting LWW and DB authority."""
        try:
            appt = self._appointments.get(change.appointment_id)
        except NotFoundError:
            _log.info(
                "inbound change for unknown appointment %s — discarding",
                change.appointment_id,
            )
            return

        # Last-write-wins: ignore an inbound edit that is not strictly newer than the DB row.
        if change.updated_at <= appt.updated_at:
            return

        if appt.status is AppointmentStatus.CANCELLED:
            return

        if change.cancelled:
            appt.cancel(now=self._clock())
            self._appointments.save(appt)
            self._notifications.appointment_cancelled(appt)
            return

        if change.new_time_range is not None and change.new_time_range != appt.time_range:
            conflicting = self._appointments.list_for_technician_between(
                appt.technician_id,
                change.new_time_range.start,
                change.new_time_range.end,
            )
            for existing in conflicting:
                if existing.id == appt.id:
                    continue
                if existing.time_range.overlaps(change.new_time_range):
                    # DB wins: the inbound edit would double-book; re-project the DB's
                    # authoritative time back onto the Google event via an UPDATE entry.
                    _log.warning(
                        "inbound reschedule for appointment %s conflicts with appointment %s "
                        "— DB wins, enqueuing re-projection UPDATE",
                        appt.id,
                        existing.id,
                    )
                    self._outbox.enqueue(OutboxOperation.UPDATE, appt.id)
                    return

            appt.reschedule(change.new_time_range, now=self._clock())
            self._appointments.save(appt)
            self._notifications.appointment_rescheduled(appt)
            return

        # Content-only edit: not a lifecycle transition, so it is reflected without a notification.
        if change.details is not None and change.details != appt.details:
            appt.add_details(change.details, now=self._clock())
            self._appointments.save(appt)
            return

        # Nothing changed: this is a projection echo of our own prior outbound update.
