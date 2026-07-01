"""Dispatcher that projects pending outbox entries to the external calendar.

CalendarProjectionDispatcher processes one outbox entry per transaction.
Each iteration: open a UoW, claim one PENDING entry (SKIP LOCKED), perform the
calendar operation, write back any side-effects (e.g. external_event_id), and
commit. A crash between the calendar call and commit leaves at most one entry
PENDING and a retry can't duplicate the event because create_event sets a
deterministic iCalUID (fsm-{appointment_id}@fsm.local) and calls import_event,
which upserts by iCalUID rather than blindly inserting.

Retry policy (see ports/outbox.py): transient failures keep the entry PENDING
(status unchanged) until MAX_ATTEMPTS is reached, at which point the entry is
dead-lettered (status FAILED). The per-entry commit means each attempt is
independently durable so no partial-batch progress is lost on a crash.

Calendar resolution is per-technician: each entry's appointment row is loaded to
determine the owning technician, and the resolver maps that technician_id to the
appropriate CalendarPort instance. This allows each technician's events to be
projected to their own provisioned calendar.
"""
from __future__ import annotations

import logging
from typing import Callable
from uuid import UUID

from fsm.scheduling.domain.appointment_context import AppointmentContext
from fsm.scheduling.ports.calendar import CalendarPort
from fsm.scheduling.ports.outbox import OutboxOperation
from fsm.scheduling.ports.unit_of_work import UnitOfWork

_log = logging.getLogger(__name__)


class CalendarProjectionDispatcher:
    """Projects pending outbox entries to the external calendar system.

    Each run_once() call claims and processes entries one at a time, each in its
    own transaction, until no PENDING entries remain (or limit is reached).
    On success an entry is marked PROCESSED; on any CalendarPort exception
    mark_failed is called, which retries transient failures up to MAX_ATTEMPTS
    before dead-lettering so one persistently-failing entry cannot stall the
    pipeline.

    Concurrent dispatcher instances are safe: claim_next uses SELECT … FOR UPDATE
    SKIP LOCKED so two dispatchers never process the same entry.

    The calendar used for each entry is resolved from the appointment's technician_id
    via the injected resolver callable so each technician's events reach their own
    calendar. Pass calendar= (a single CalendarPort) as a convenience shortcut; it is
    silently wrapped into a resolver that always returns the same port.
    """

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        calendar: CalendarPort | None = None,
        *,
        calendar_resolver: Callable[[UUID], CalendarPort] | None = None,
        on_calendar_error: Callable[[UUID, Exception], None] | None = None,
        customer_name_resolver: Callable[[UUID], str | None] | None = None,
    ) -> None:
        if calendar is None and calendar_resolver is None:
            raise ValueError(
                "Provide exactly one of calendar= or calendar_resolver=; neither was given."
            )
        if calendar is not None and calendar_resolver is not None:
            raise ValueError(
                "Provide exactly one of calendar= or calendar_resolver=; both were given."
            )
        self._uow_factory = uow_factory
        self._resolver: Callable[[UUID], CalendarPort]
        if calendar is not None:
            self._resolver = lambda _technician_id: calendar
        else:
            self._resolver = calendar_resolver  # type: ignore[assignment]
        self._on_calendar_error = on_calendar_error
        self._customer_name_resolver: Callable[[UUID], str | None] = (
            customer_name_resolver if customer_name_resolver is not None else (lambda _customer_id: None)
        )

    def _build_context(self, uow: UnitOfWork, appt) -> AppointmentContext:
        """Assemble enrichment context from the service call and the customer-name resolver."""
        service_call = uow.service_calls.get(appt.service_call_id)
        return AppointmentContext(
            customer_name=self._customer_name_resolver(appt.customer_id),
            problem_description=service_call.description,
        )

    def run_once(self, limit: int = 50) -> int:
        """Claim and process up to `limit` pending outbox entries; return the count processed."""
        processed = 0
        for _ in range(limit):
            claimed = self._process_one()
            if claimed is False:
                break
            if claimed is True:
                processed += 1
        return processed

    def _process_one(self) -> bool | None:
        """Claim and process one entry in its own transaction.

        Returns True if the entry was processed successfully, False if the queue is
        empty, and None if the entry was failed/skipped (not counted as processed).
        """
        with self._uow_factory() as uow:
            entry = uow.outbox.claim_next()
            if entry is None:
                return False

            technician_id: UUID | None = None
            try:
                appt = uow.appointments.get(entry.appointment_id)
                technician_id = appt.technician_id
                calendar = self._resolver(technician_id)

                if entry.operation is OutboxOperation.CREATE:
                    context = self._build_context(uow, appt)
                    event_id = calendar.create_event(appt, context)
                    appt.assign_external_event(event_id)
                    uow.appointments.save(appt)
                    uow.outbox.mark_processed(entry.id)
                    uow.commit()
                    return True

                elif entry.operation is OutboxOperation.UPDATE:
                    if appt.external_event_id is None:
                        _log.debug(
                            "UPDATE entry %s skipped: CREATE not yet processed for appointment %s",
                            entry.id,
                            entry.appointment_id,
                        )
                        uow.outbox.mark_failed(
                            entry.id,
                            "UPDATE skipped: CREATE not yet processed (no external_event_id)",
                        )
                        uow.commit()
                        return None
                    context = self._build_context(uow, appt)
                    calendar.update_event(appt.external_event_id, appt, context)
                    uow.outbox.mark_processed(entry.id)
                    uow.commit()
                    return True

                elif entry.operation is OutboxOperation.DELETE:
                    if entry.external_event_id is not None:
                        calendar.delete_event(entry.external_event_id)
                    # A DELETE for a never-created event is a no-op; mark processed either way.
                    uow.outbox.mark_processed(entry.id)
                    uow.commit()
                    return True

            except Exception as exc:
                _log.warning(
                    "CalendarPort error processing outbox entry %s (operation=%s): %s",
                    entry.id,
                    entry.operation.value,
                    exc,
                )
                uow.outbox.mark_failed(entry.id, str(exc))
                uow.commit()
                if technician_id is not None and self._on_calendar_error is not None:
                    try:
                        self._on_calendar_error(technician_id, exc)
                    except Exception:
                        _log.exception(
                            "on_calendar_error callback raised for technician %s; ignoring",
                            technician_id,
                        )
                return None

        return None
