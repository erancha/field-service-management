"""One-time backfill: enqueue a re-projection UPDATE for active future appointments so the
existing customer becomes a guest on their FSM event.

Data-safe to re-run — a repeat UPDATE for an already-attended event re-projects the same state —
but each UPDATE projects with sendUpdates=all, so re-running re-emails every active customer.
Intended to run once, after the attendee model ships.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from fsm.scheduling.adapters.orm import AppointmentRow
from fsm.scheduling.adapters.outbox_repository import SqlAlchemyOutboxRepository
from fsm.scheduling.ports.outbox import OutboxOperation


def enqueue_attendee_backfill(session, *, now: datetime) -> int:
    """Enqueue an UPDATE for every active, future, already-projected appointment. Return the count."""
    appointment_ids = session.execute(
        select(AppointmentRow.id).where(
            AppointmentRow.status != "CANCELLED",
            AppointmentRow.start_at > now,
            AppointmentRow.external_event_id.is_not(None),
        )
    ).scalars().all()
    outbox = SqlAlchemyOutboxRepository(session)
    for appointment_id in appointment_ids:
        outbox.enqueue(OutboxOperation.UPDATE, appointment_id)
    return len(appointment_ids)


if __name__ == "__main__":
    from datetime import timezone

    from fsm.core.db import session_factory
    from fsm.platform.config import get_settings
    from fsm.platform.db import create_engine_from_settings
    from fsm.platform.logging import configure_logging

    configure_logging()
    settings = get_settings()
    factory = session_factory(create_engine_from_settings(settings))
    with factory() as s:
        with s.begin():
            n = enqueue_attendee_backfill(s, now=datetime.now(timezone.utc))
    print(f"Enqueued {n} attendee-backfill UPDATE(s)")
