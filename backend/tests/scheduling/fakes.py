"""In-memory fake implementations of the scheduling port protocols.

These fakes are test-support only and are never shipped as part of the production
package. They satisfy each protocol structurally and can be verified with
isinstance checks because every protocol is @runtime_checkable.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from fsm.scheduling.domain.appointment import Appointment, AppointmentStatus
from fsm.scheduling.domain.appointment_context import AppointmentContext
from fsm.scheduling.domain.errors import NotFoundError
from fsm.scheduling.domain.service_call import ServiceCall
from fsm.scheduling.domain.time_range import TimeRange
from fsm.scheduling.ports.outbox import MAX_ATTEMPTS, OutboxEntry, OutboxOperation


class InMemoryServiceCallRepository:
    """Dict-backed ServiceCallRepository. Stores references; mutations visible immediately."""

    def __init__(self) -> None:
        self._store: dict[UUID, ServiceCall] = {}

    def add(self, service_call: ServiceCall) -> None:
        self._store[service_call.id] = service_call

    def get(self, service_call_id: UUID) -> ServiceCall:
        try:
            return self._store[service_call_id]
        except KeyError:
            raise NotFoundError(f"ServiceCall {service_call_id!r} not found")

    def save(self, service_call: ServiceCall) -> None:
        self._store[service_call.id] = service_call


class InMemoryAppointmentRepository:
    """Dict-backed AppointmentRepository.

    list_for_technician_between filters by technician, excludes CANCELLED, and
    returns only appointments whose time_range overlaps [start, end).

    audits collects (appointment_id, action, occurred_at) tuples drained from each
    appointment on add/save, mirroring the SQL adapter's audit drain contract.
    """

    def __init__(self) -> None:
        self._store: dict[UUID, Appointment] = {}
        self.audits: list[tuple[Any, Any, Any]] = []

    def add(self, appointment: Appointment) -> None:
        self._store[appointment.id] = appointment
        self._drain_audits(appointment)

    def get(self, appointment_id: UUID) -> Appointment:
        try:
            return self._store[appointment_id]
        except KeyError:
            raise NotFoundError(f"Appointment {appointment_id!r} not found")

    def save(self, appointment: Appointment) -> None:
        self._store[appointment.id] = appointment
        self._drain_audits(appointment)

    def _drain_audits(self, appointment: Appointment) -> None:
        for record in appointment.drain_audits():
            self.audits.append((appointment.id, record.action, record.occurred_at))

    def list_for_technician_between(
        self,
        technician_id: UUID,
        start: datetime,
        end: datetime,
    ) -> list[Appointment]:
        window = TimeRange(start=start, end=end)
        return [
            appt
            for appt in self._store.values()
            if appt.technician_id == technician_id
            and appt.status is not AppointmentStatus.CANCELLED
            and appt.time_range.overlaps(window)
        ]


class _FakeHttp409(Exception):
    """Duck-types googleapiclient.errors.HttpError's resp.status for a 409 duplicate."""

    def __init__(self) -> None:
        self.resp = type("R", (), {"status": 409})()


class FakeGoogleCalendarClient:
    """In-memory GoogleCalendarClient for unit tests.

    insert_event raises a fake HTTP 409 on a duplicate iCalUID, matching the real
    events.insert behavior; find_event_id_by_ical_uid recovers the existing id so a
    retried CREATE resolves to the same event id rather than duplicating.
    update_event reuses the supplied event id.
    """

    def __init__(self) -> None:
        self._counter: int = 0
        self._events: dict[str, dict] = {}
        self._by_ical_uid: dict[str, str] = {}
        self.updated: list[tuple[str, dict]] = []
        self.deleted: list[str] = []
        self.inserted: list[dict] = []

    def insert_event(self, calendar_id: str, body: dict, *, send_updates: str = "all") -> dict:
        """Create a new event; raise a fake HTTP 409 if the iCalUID already exists."""
        ical_uid = body.get("iCalUID", "")
        if ical_uid in self._by_ical_uid:
            raise _FakeHttp409()
        self._counter += 1
        event_id = f"evt-{self._counter}"
        self._by_ical_uid[ical_uid] = event_id
        stored = dict(body, id=event_id)
        self._events[event_id] = stored
        self.inserted.append(stored)
        return stored

    def find_event_id_by_ical_uid(self, calendar_id: str, ical_uid: str) -> str | None:
        return self._by_ical_uid.get(ical_uid)

    def update_event(
        self, calendar_id: str, event_id: str, body: dict, *, send_updates: str = "all"
    ) -> dict:
        stored = dict(body, id=event_id)
        self._events[event_id] = stored
        self.updated.append((event_id, stored))
        return stored

    def delete_event(self, calendar_id: str, event_id: str, *, send_updates: str = "all") -> None:
        self._events.pop(event_id, None)
        self.deleted.append(event_id)

    def query_busy(self, calendar_id: str, time_min: datetime, time_max: datetime) -> list:
        return []

    def create_calendar(self, summary: str) -> str:
        self._counter += 1
        return f"cal-{self._counter}"


class FakeCalendarPort:
    """In-memory CalendarPort.

    Busy ranges per technician are set explicitly via set_busy. Created/updated/deleted
    events are recorded in public attributes for assertion in tests. Event ids are
    deterministic sequential strings (evt-1, evt-2, ...) using a counter.

    create_event upserts by iCalUID: a retried CREATE with the same iCalUID returns
    the original event id, preventing duplicate calendar events on retry.
    """

    def __init__(self) -> None:
        self._busy: dict[UUID, list[TimeRange]] = {}
        self._counter: int = 0
        self._ical_uid_to_event_id: dict[str, str] = {}
        self.created_events: dict[str, Appointment] = {}
        self.updated_events: dict[str, Appointment] = {}
        self.created_contexts: dict[str, AppointmentContext] = {}
        self.updated_contexts: dict[str, AppointmentContext] = {}
        self.deleted_event_ids: list[str] = []
        self.create_calls: list[tuple[str, Appointment]] = []

    def set_busy(self, technician_id: UUID, ranges: list[TimeRange]) -> None:
        """Replace the busy interval list for a technician (test helper)."""
        self._busy[technician_id] = list(ranges)

    def get_busy(
        self,
        technician_id: UUID,
        start: datetime,
        end: datetime,
    ) -> list[TimeRange]:
        return list(self._busy.get(technician_id, []))

    def create_event(self, appointment: Appointment, context: AppointmentContext) -> str:
        ical_uid = f"fsm-{appointment.id}@fsm.local"
        if ical_uid in self._ical_uid_to_event_id:
            event_id = self._ical_uid_to_event_id[ical_uid]
        else:
            self._counter += 1
            event_id = f"evt-{self._counter}"
            self._ical_uid_to_event_id[ical_uid] = event_id
        self.created_events[event_id] = appointment
        self.created_contexts[event_id] = context
        self.create_calls.append((event_id, appointment))
        return event_id

    def update_event(self, external_event_id: str, appointment: Appointment, context: AppointmentContext) -> None:
        self.updated_events[external_event_id] = appointment
        self.updated_contexts[external_event_id] = context

    def delete_event(self, external_event_id: str) -> None:
        self.deleted_event_ids.append(external_event_id)


class InMemoryOutboxRepository:
    """In-memory OutboxRepository for unit tests.

    Enqueued entries are stored in insertion order. mark_processed and mark_failed
    update their status in-place so dispatcher tests can verify the final state.

    Retry policy mirrors the production adapter: mark_failed keeps status PENDING
    while attempts < MAX_ATTEMPTS; at the cap it transitions to terminal FAILED.
    claim_next returns the oldest PENDING entry (FIFO, non-blocking — no locking needed
    in a single-threaded fake).
    """

    def __init__(self) -> None:
        self._entries: list[OutboxEntry] = []
        self._statuses: dict[UUID, str] = {}
        self._errors: dict[UUID, str] = {}
        self._attempts: dict[UUID, int] = {}

    def clear(self) -> None:
        """Reset all state — use in tests instead of accessing private attributes."""
        self._entries.clear()
        self._statuses.clear()
        self._errors.clear()
        self._attempts.clear()

    def enqueue(
        self,
        operation: OutboxOperation,
        appointment_id: UUID,
        external_event_id: str | None = None,
    ) -> None:
        entry = OutboxEntry(
            id=uuid4(),
            operation=operation,
            appointment_id=appointment_id,
            external_event_id=external_event_id,
            attempts=0,
        )
        self._entries.append(entry)
        self._statuses[entry.id] = "PENDING"
        self._attempts[entry.id] = 0

    def claim_next(self) -> OutboxEntry | None:
        """Return the oldest PENDING entry, or None if the queue is empty."""
        for entry in self._entries:
            if self._statuses.get(entry.id) == "PENDING":
                attempts = self._attempts.get(entry.id, 0)
                return OutboxEntry(
                    id=entry.id,
                    operation=entry.operation,
                    appointment_id=entry.appointment_id,
                    external_event_id=entry.external_event_id,
                    attempts=attempts,
                )
        return None

    def list_pending(self, limit: int) -> list[OutboxEntry]:
        pending = [e for e in self._entries if self._statuses.get(e.id) == "PENDING"]
        return pending[:limit]

    def mark_processed(self, entry_id: UUID) -> None:
        if entry_id not in self._statuses:
            raise NotFoundError(f"OutboxEntry {entry_id!r} not found")
        self._statuses[entry_id] = "PROCESSED"

    def mark_failed(self, entry_id: UUID, error: str) -> None:
        if entry_id not in self._statuses:
            raise NotFoundError(f"OutboxEntry {entry_id!r} not found")
        new_attempts = self._attempts.get(entry_id, 0) + 1
        self._attempts[entry_id] = new_attempts
        self._errors[entry_id] = error
        if new_attempts >= MAX_ATTEMPTS:
            self._statuses[entry_id] = "FAILED"

    def get_status(self, entry_id: UUID) -> str | None:
        return self._statuses.get(entry_id)

    def get_attempts(self, entry_id: UUID) -> int:
        return self._attempts.get(entry_id, 0)

    @property
    def all_entries(self) -> list[OutboxEntry]:
        return list(self._entries)

    @property
    def pending_entries(self) -> list[OutboxEntry]:
        return [e for e in self._entries if self._statuses.get(e.id) == "PENDING"]


class FakeNotificationPort:
    """Records appointment notification calls as (kind, appointment) tuples.

    Attribute `calls` holds each invocation in the order it was received.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, Appointment]] = []

    def appointment_booked(self, appointment: Appointment) -> None:
        self.calls.append(("booked", appointment))

    def appointment_rescheduled(self, appointment: Appointment) -> None:
        self.calls.append(("rescheduled", appointment))

    def appointment_updated(self, appointment: Appointment) -> None:
        self.calls.append(("updated", appointment))

    def appointment_cancelled(self, appointment: Appointment) -> None:
        self.calls.append(("cancelled", appointment))


class _RollbackableOutboxProxy:
    """Wraps InMemoryOutboxRepository and buffers mutations until flush() is called.

    claim_next delegates immediately (read-only). mark_processed / mark_failed
    are recorded as pending mutations; flush() applies them atomically.
    rollback() discards pending mutations.
    """

    def __init__(self, real: "InMemoryOutboxRepository") -> None:
        self._real = real
        self._pending: list[tuple[str, object, object]] = []

    def enqueue(self, operation: OutboxOperation, appointment_id: UUID, external_event_id: str | None = None) -> None:
        self._real.enqueue(operation, appointment_id, external_event_id)

    def claim_next(self) -> OutboxEntry | None:
        return self._real.claim_next()

    def list_pending(self, limit: int) -> list[OutboxEntry]:
        return self._real.list_pending(limit)

    def mark_processed(self, entry_id: UUID) -> None:
        if entry_id not in self._real._statuses:
            raise NotFoundError(f"OutboxEntry {entry_id!r} not found")
        # Remove any prior mutation for this entry before recording the new one.
        self._pending = [(op, eid, arg) for op, eid, arg in self._pending if eid != entry_id]
        self._pending.append(("mark_processed", entry_id, None))

    def mark_failed(self, entry_id: UUID, error: str) -> None:
        if entry_id not in self._real._statuses:
            raise NotFoundError(f"OutboxEntry {entry_id!r} not found")
        # Remove any prior mutation for this entry (e.g. a mark_processed that didn't commit).
        self._pending = [(op, eid, arg) for op, eid, arg in self._pending if eid != entry_id]
        self._pending.append(("mark_failed", entry_id, error))

    def flush(self) -> None:
        for op, entry_id, arg in self._pending:
            if op == "mark_processed":
                self._real.mark_processed(entry_id)  # type: ignore[arg-type]
            elif op == "mark_failed":
                self._real.mark_failed(entry_id, arg)  # type: ignore[arg-type]
        self._pending.clear()

    def rollback(self) -> None:
        self._pending.clear()

    def get_status(self, entry_id: UUID) -> str | None:
        return self._real.get_status(entry_id)

    def get_attempts(self, entry_id: UUID) -> int:
        return self._real.get_attempts(entry_id)


class _RollbackableAppointmentProxy:
    """Wraps InMemoryAppointmentRepository and buffers save() calls until flush()."""

    def __init__(self, real: "InMemoryAppointmentRepository") -> None:
        self._real = real
        self._pending_saves: list["Appointment"] = []

    def add(self, appointment: "Appointment") -> None:
        self._real.add(appointment)

    def get(self, appointment_id: UUID) -> "Appointment":
        return self._real.get(appointment_id)

    def save(self, appointment: "Appointment") -> None:
        self._pending_saves.append(appointment)

    def list_for_technician_between(self, technician_id: UUID, start: "datetime", end: "datetime") -> list:
        return self._real.list_for_technician_between(technician_id, start, end)

    def flush(self) -> None:
        for appt in self._pending_saves:
            self._real.save(appt)
        self._pending_saves.clear()

    def rollback(self) -> None:
        self._pending_saves.clear()


class FakeUnitOfWork:
    """In-memory UnitOfWork for dispatcher unit tests.

    Wraps InMemoryOutboxRepository and InMemoryAppointmentRepository with
    transaction-scoped proxy objects that buffer mutations. commit() applies all
    buffered mutations atomically; a raised exception before commit rolls back
    without applying any changes. Set commit_raises_once=True to simulate a crash
    between the calendar call and the commit.
    """

    def __init__(
        self,
        outbox: "InMemoryOutboxRepository",
        appointments: "InMemoryAppointmentRepository",
        service_calls: "InMemoryServiceCallRepository | None" = None,
    ) -> None:
        self._outbox_real = outbox
        self._appointments_real = appointments
        self.service_calls = service_calls if service_calls is not None else InMemoryServiceCallRepository()
        self.commit_raises_once: bool = False
        self._raise_on_next_commit: bool = False
        self.outbox: _RollbackableOutboxProxy = _RollbackableOutboxProxy(outbox)
        self.appointments: _RollbackableAppointmentProxy = _RollbackableAppointmentProxy(appointments)

    def __enter__(self) -> "FakeUnitOfWork":
        self.outbox = _RollbackableOutboxProxy(self._outbox_real)
        self.appointments = _RollbackableAppointmentProxy(self._appointments_real)
        if self.commit_raises_once:
            self._raise_on_next_commit = True
            self.commit_raises_once = False
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        self.outbox.rollback()
        self.appointments.rollback()

    def commit(self) -> None:
        if self._raise_on_next_commit:
            self._raise_on_next_commit = False
            raise RuntimeError("simulated crash at commit")
        self.outbox.flush()
        self.appointments.flush()
