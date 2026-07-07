"""Re-project a technician's active appointments onto a freshly provisioned FSM calendar.

When a technician's calendar is provisioned anew — because the previous one was deleted in Google —
the appointments held in this system still reference events on the calendar that no longer exists.
Enqueuing a CREATE for each active, future appointment lets the calendar dispatcher rebuild those
events on the new calendar and repoint each appointment's external_event_id.

Only the composition root reaches across the scheduling boundary like this, so the action lives in
platform rather than inside either bounded context.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select

from fsm.scheduling.adapters.orm import AppointmentRow
from fsm.scheduling.adapters.outbox_repository import SqlAlchemyOutboxRepository
from fsm.scheduling.domain.appointment import AppointmentStatus
from fsm.scheduling.ports.outbox import OutboxOperation


def reproject_active_appointments(session, technician_id: UUID, *, now: datetime) -> int:
    """Enqueue a CREATE for each of the technician's active, future appointments; return the count.

    Past and cancelled appointments are skipped: a deleted calendar only needs its still-relevant
    upcoming events rebuilt. The caller owns the transaction, so the enqueued rows commit with it.
    """
    appointment_ids = session.execute(
        select(AppointmentRow.id).where(
            AppointmentRow.technician_id == technician_id,
            AppointmentRow.status != AppointmentStatus.CANCELLED.value,
            AppointmentRow.start_at > now,
        )
    ).scalars().all()
    outbox = SqlAlchemyOutboxRepository(session)
    for appointment_id in appointment_ids:
        outbox.enqueue(OutboxOperation.CREATE, appointment_id)
    return len(appointment_ids)
