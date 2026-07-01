"""Unit tests for CalendarProjectionDispatcher using in-memory fakes."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest

from fsm.scheduling.application.calendar_projection_dispatcher import CalendarProjectionDispatcher
from fsm.scheduling.domain.appointment import Appointment, AppointmentStatus
from fsm.scheduling.domain.appointment_context import AppointmentContext
from fsm.scheduling.domain.service_call import ServiceCall, ServiceCallStatus
from fsm.scheduling.domain.time_range import TimeRange
from fsm.scheduling.ports.outbox import MAX_ATTEMPTS, OutboxOperation
from tests.scheduling.fakes import (
    FakeCalendarPort,
    FakeUnitOfWork,
    InMemoryAppointmentRepository,
    InMemoryOutboxRepository,
    InMemoryServiceCallRepository,
)

_TZ = timezone.utc
_NOW = datetime(2024, 6, 10, 8, 0, tzinfo=_TZ)
_TECH_ID = UUID("cccccccc-0000-0000-0000-000000000001")
_CUST_ID = UUID("dddddddd-0000-0000-0000-000000000001")
_SC_ID = UUID("bbbbbbbb-0000-0000-0000-000000000001")
_CUSTOMER_NAME = "Ada Lovelace"
_PROBLEM = "No hot water"


def _make_appointment(appt_id: UUID, external_event_id: str | None = None) -> Appointment:
    return Appointment(
        id=appt_id,
        service_call_id=_SC_ID,
        technician_id=_TECH_ID,
        customer_id=_CUST_ID,
        time_range=TimeRange(
            start=datetime(2024, 6, 10, 9, 0, tzinfo=_TZ),
            end=datetime(2024, 6, 10, 11, 0, tzinfo=_TZ),
        ),
        status=AppointmentStatus.SCHEDULED,
        details=None,
        external_event_id=external_event_id,
        created_at=_NOW,
        updated_at=_NOW,
    )


@pytest.fixture
def appt_repo() -> InMemoryAppointmentRepository:
    return InMemoryAppointmentRepository()


@pytest.fixture
def outbox() -> InMemoryOutboxRepository:
    return InMemoryOutboxRepository()


@pytest.fixture
def calendar() -> FakeCalendarPort:
    return FakeCalendarPort()


@pytest.fixture
def service_calls() -> InMemoryServiceCallRepository:
    repo = InMemoryServiceCallRepository()
    repo.add(
        ServiceCall(
            id=_SC_ID,
            customer_id=_CUST_ID,
            description=_PROBLEM,
            status=ServiceCallStatus.SCHEDULED,
            created_at=_NOW,
        )
    )
    return repo


@pytest.fixture
def uow(
    outbox: InMemoryOutboxRepository,
    appt_repo: InMemoryAppointmentRepository,
    service_calls: InMemoryServiceCallRepository,
) -> FakeUnitOfWork:
    return FakeUnitOfWork(outbox=outbox, appointments=appt_repo, service_calls=service_calls)


@pytest.fixture
def dispatcher(
    uow: FakeUnitOfWork,
    calendar: FakeCalendarPort,
) -> CalendarProjectionDispatcher:
    return CalendarProjectionDispatcher(
        uow_factory=lambda: uow,
        calendar=calendar,
        customer_name_resolver=lambda _customer_id: _CUSTOMER_NAME,
    )


class TestCreateEntry:
    def test_create_entry_calls_calendar_and_sets_external_event_id(
        self,
        dispatcher: CalendarProjectionDispatcher,
        appt_repo: InMemoryAppointmentRepository,
        outbox: InMemoryOutboxRepository,
        calendar: FakeCalendarPort,
    ):
        """A CREATE outbox entry results in a calendar.create_event call and
        sets external_event_id on the appointment row."""
        appt_id = UUID("aaaaaaaa-0000-0000-0000-000000000001")
        appt_repo.add(_make_appointment(appt_id))
        outbox.enqueue(OutboxOperation.CREATE, appt_id)

        count = dispatcher.run_once()

        assert count == 1
        assert len(calendar.created_events) == 1
        stored = appt_repo.get(appt_id)
        assert stored.external_event_id is not None
        assert stored.external_event_id in calendar.created_events

    def test_create_entry_is_marked_processed(
        self,
        dispatcher: CalendarProjectionDispatcher,
        appt_repo: InMemoryAppointmentRepository,
        outbox: InMemoryOutboxRepository,
    ):
        appt_id = UUID("aaaaaaaa-0000-0000-0000-000000000002")
        appt_repo.add(_make_appointment(appt_id))
        outbox.enqueue(OutboxOperation.CREATE, appt_id)

        entry_id = outbox.all_entries[0].id
        dispatcher.run_once()

        assert outbox.get_status(entry_id) == "PROCESSED"

    def test_commit_failure_after_create_leaves_entry_pending_and_no_duplicate(
        self,
        uow: FakeUnitOfWork,
        appt_repo: InMemoryAppointmentRepository,
        outbox: InMemoryOutboxRepository,
        calendar: FakeCalendarPort,
    ):
        """Simulates a commit failure after create_event — models the at-most-one-duplicate window.

        When the DB commit raises after the calendar event is created, the entry stays PENDING
        (mark_processed never committed). The dispatcher treats the commit error as a transient
        failure, bumps attempts, and keeps the entry PENDING for retry.

        On the retry, create_event is called again. Because create_event uses import_event with
        a deterministic iCalUID (fsm-{appointment_id}@fsm.local), the Google Calendar API
        upserts rather than inserts — the iCalUID upsert returns the same event id, so no
        duplicate calendar event is created. The fake verifies this property.
        """
        appt_id = UUID("aaaaaaaa-0000-0000-0000-000000000009")
        appt_repo.add(_make_appointment(appt_id))
        outbox.enqueue(OutboxOperation.CREATE, appt_id)
        entry_id = outbox.all_entries[0].id

        # First run (limit=1): commit raises — entry stays PENDING with attempts bumped.
        uow.commit_raises_once = True
        dispatcher = CalendarProjectionDispatcher(uow_factory=lambda: uow, calendar=calendar)
        count = dispatcher.run_once(limit=1)

        # Entry must still be PENDING (commit failure means mark_processed didn't land).
        assert outbox.get_status(entry_id) == "PENDING"
        assert count == 0

        # Second run (limit=1): succeeds. create_event was called twice (once per run).
        count2 = dispatcher.run_once(limit=1)
        assert count2 == 1
        assert outbox.get_status(entry_id) == "PROCESSED"
        assert len(calendar.import_calls) == 2, "create_event (import_event) called twice across two runs"
        # Both calls returned the same event id — no duplicate event.
        event_ids = {event_id for event_id, _ in calendar.import_calls}
        assert len(event_ids) == 1, "Both calls resolved to the same event id (iCalUID upsert)"


class TestUpdateEntry:
    def test_update_entry_calls_calendar_update_when_event_id_present(
        self,
        dispatcher: CalendarProjectionDispatcher,
        appt_repo: InMemoryAppointmentRepository,
        outbox: InMemoryOutboxRepository,
        calendar: FakeCalendarPort,
    ):
        """An UPDATE entry calls update_event when the appointment has an external_event_id."""
        appt_id = UUID("aaaaaaaa-0000-0000-0000-000000000003")
        appt_repo.add(_make_appointment(appt_id, external_event_id="evt-existing"))
        outbox.enqueue(OutboxOperation.UPDATE, appt_id)

        count = dispatcher.run_once()

        assert count == 1
        assert "evt-existing" in calendar.updated_events

    def test_update_before_create_increments_attempts(
        self,
        dispatcher: CalendarProjectionDispatcher,
        appt_repo: InMemoryAppointmentRepository,
        outbox: InMemoryOutboxRepository,
        calendar: FakeCalendarPort,
    ):
        """An UPDATE entry for an appointment with no external_event_id bumps attempts
        via mark_failed so it eventually dead-letters if CREATE never completes."""
        appt_id = UUID("aaaaaaaa-0000-0000-0000-000000000004")
        appt_repo.add(_make_appointment(appt_id, external_event_id=None))
        outbox.enqueue(OutboxOperation.UPDATE, appt_id)

        entry_id = outbox.all_entries[0].id
        count = dispatcher.run_once(limit=1)

        assert count == 0
        assert outbox.get_attempts(entry_id) == 1
        assert len(calendar.updated_events) == 0

    def test_update_without_create_eventually_dead_letters(
        self,
        dispatcher: CalendarProjectionDispatcher,
        appt_repo: InMemoryAppointmentRepository,
        outbox: InMemoryOutboxRepository,
    ):
        """An UPDATE whose CREATE never succeeds is dead-lettered after MAX_ATTEMPTS runs."""
        appt_id = UUID("aaaaaaaa-0000-0000-0000-000000000010")
        appt_repo.add(_make_appointment(appt_id, external_event_id=None))
        outbox.enqueue(OutboxOperation.UPDATE, appt_id)
        entry_id = outbox.all_entries[0].id

        for _ in range(MAX_ATTEMPTS):
            dispatcher.run_once()

        assert outbox.get_status(entry_id) == "FAILED"
        assert outbox.get_attempts(entry_id) == MAX_ATTEMPTS

    def test_update_without_create_not_selected_after_dead_letter(
        self,
        dispatcher: CalendarProjectionDispatcher,
        appt_repo: InMemoryAppointmentRepository,
        outbox: InMemoryOutboxRepository,
    ):
        """After dead-lettering the entry is no longer returned by claim_next."""
        appt_id = UUID("aaaaaaaa-0000-0000-0000-000000000011")
        appt_repo.add(_make_appointment(appt_id, external_event_id=None))
        outbox.enqueue(OutboxOperation.UPDATE, appt_id)

        for _ in range(MAX_ATTEMPTS):
            dispatcher.run_once()

        # No more PENDING entries.
        assert outbox.claim_next() is None


class TestDeleteEntry:
    def test_delete_entry_calls_calendar_delete_when_event_id_present(
        self,
        dispatcher: CalendarProjectionDispatcher,
        appt_repo: InMemoryAppointmentRepository,
        outbox: InMemoryOutboxRepository,
        calendar: FakeCalendarPort,
    ):
        appt_id = UUID("aaaaaaaa-0000-0000-0000-000000000005")
        appt_repo.add(_make_appointment(appt_id))
        outbox.enqueue(OutboxOperation.DELETE, appt_id, external_event_id="evt-to-delete")

        count = dispatcher.run_once()

        assert count == 1
        assert "evt-to-delete" in calendar.deleted_event_ids

    def test_delete_without_event_id_is_noop_and_marked_processed(
        self,
        dispatcher: CalendarProjectionDispatcher,
        appt_repo: InMemoryAppointmentRepository,
        outbox: InMemoryOutboxRepository,
        calendar: FakeCalendarPort,
    ):
        """A DELETE for a never-created event has no external_event_id; it is a no-op."""
        appt_id = UUID("aaaaaaaa-0000-0000-0000-000000000006")
        appt_repo.add(_make_appointment(appt_id))
        outbox.enqueue(OutboxOperation.DELETE, appt_id, external_event_id=None)

        entry_id = outbox.all_entries[0].id
        count = dispatcher.run_once()

        assert count == 1
        assert len(calendar.deleted_event_ids) == 0
        assert outbox.get_status(entry_id) == "PROCESSED"


class TestCalendarExceptionHandling:
    def test_calendar_exception_marks_entry_retryable_on_first_failure(
        self,
        appt_repo: InMemoryAppointmentRepository,
        outbox: InMemoryOutboxRepository,
        uow: FakeUnitOfWork,
    ):
        """A CalendarPort exception bumps attempts but keeps the entry PENDING (retryable)
        until the cap; only one attempt per run_once(limit=1) call."""

        class BrokenCalendar:
            def get_busy(self, *a, **kw):
                return []

            def create_event(self, appt, context):
                raise RuntimeError("calendar unavailable")

            def update_event(self, eid, appt, context):
                pass

            def delete_event(self, eid):
                pass

        dispatcher = CalendarProjectionDispatcher(
            uow_factory=lambda: uow,
            calendar=BrokenCalendar(),
        )

        appt_id_bad = UUID("aaaaaaaa-0000-0000-0000-000000000007")
        appt_repo.add(_make_appointment(appt_id_bad))
        outbox.enqueue(OutboxOperation.CREATE, appt_id_bad)

        bad_entry_id = outbox.all_entries[0].id

        # One run attempt: entry is still PENDING with 1 attempt.
        count = dispatcher.run_once(limit=1)

        assert count == 0
        assert outbox.get_status(bad_entry_id) == "PENDING"
        assert outbox.get_attempts(bad_entry_id) == 1

    def test_dead_lettered_entry_no_longer_blocks_subsequent_entries(
        self,
        appt_repo: InMemoryAppointmentRepository,
        outbox: InMemoryOutboxRepository,
        uow: FakeUnitOfWork,
    ):
        """Once a persistently-failing entry is dead-lettered (FAILED) after MAX_ATTEMPTS,
        subsequent PENDING entries become the oldest and are processed normally."""

        class SelectivelyBrokenCalendar:
            def get_busy(self, *a, **kw):
                return []

            def create_event(self, appt, context):
                raise RuntimeError("calendar unavailable")

            def update_event(self, eid, appt, context):
                pass

            def delete_event(self, eid):
                pass

        dispatcher = CalendarProjectionDispatcher(
            uow_factory=lambda: uow,
            calendar=SelectivelyBrokenCalendar(),
        )

        appt_id_bad = UUID("aaaaaaaa-0000-0000-0000-000000000007")
        appt_id_ok = UUID("aaaaaaaa-0000-0000-0000-000000000008")
        appt_repo.add(_make_appointment(appt_id_bad))
        appt_repo.add(_make_appointment(appt_id_ok, external_event_id="evt-ok"))

        outbox.enqueue(OutboxOperation.CREATE, appt_id_bad)
        outbox.enqueue(OutboxOperation.DELETE, appt_id_ok, external_event_id="evt-ok")

        bad_entry_id = outbox.all_entries[0].id
        ok_entry_id = outbox.all_entries[1].id

        # Run with enough iterations to dead-letter the bad entry (MAX_ATTEMPTS) and
        # then process the DELETE (1 more).
        count = dispatcher.run_once(limit=MAX_ATTEMPTS + 1)

        assert count == 1
        assert outbox.get_status(bad_entry_id) == "FAILED"
        assert outbox.get_attempts(bad_entry_id) == MAX_ATTEMPTS
        assert outbox.get_status(ok_entry_id) == "PROCESSED"

    def test_transient_failure_retried_on_next_run(
        self,
        appt_repo: InMemoryAppointmentRepository,
        outbox: InMemoryOutboxRepository,
        uow: FakeUnitOfWork,
    ):
        """An entry that fails once is retried on the next run when the calendar recovers."""
        fail_count = {"n": 0}

        class FlakyCalendar:
            def get_busy(self, *a, **kw):
                return []

            def create_event(self, appt, context):
                if fail_count["n"] == 0:
                    fail_count["n"] += 1
                    raise RuntimeError("transient error")
                return "evt-recovered"

            def update_event(self, eid, appt, context):
                pass

            def delete_event(self, eid):
                pass

        dispatcher = CalendarProjectionDispatcher(
            uow_factory=lambda: uow,
            calendar=FlakyCalendar(),
        )
        appt_id = UUID("aaaaaaaa-0000-0000-0000-000000000012")
        appt_repo.add(_make_appointment(appt_id))
        outbox.enqueue(OutboxOperation.CREATE, appt_id)
        entry_id = outbox.all_entries[0].id

        # First run (limit=1): fails transiently, entry stays PENDING.
        dispatcher.run_once(limit=1)
        assert outbox.get_status(entry_id) == "PENDING"
        assert outbox.get_attempts(entry_id) == 1

        # Second run (limit=1): calendar recovers, entry is processed.
        dispatcher.run_once(limit=1)
        assert outbox.get_status(entry_id) == "PROCESSED"

    def test_persistent_failure_dead_letters_at_cap(
        self,
        appt_repo: InMemoryAppointmentRepository,
        outbox: InMemoryOutboxRepository,
        uow: FakeUnitOfWork,
    ):
        """After MAX_ATTEMPTS failures the entry is dead-lettered (FAILED) and no longer selected."""

        class AlwaysBrokenCalendar:
            def get_busy(self, *a, **kw):
                return []

            def create_event(self, appt, context):
                raise RuntimeError("always broken")

            def update_event(self, eid, appt, context):
                pass

            def delete_event(self, eid):
                pass

        dispatcher = CalendarProjectionDispatcher(
            uow_factory=lambda: uow,
            calendar=AlwaysBrokenCalendar(),
        )
        appt_id = UUID("aaaaaaaa-0000-0000-0000-000000000013")
        appt_repo.add(_make_appointment(appt_id))
        outbox.enqueue(OutboxOperation.CREATE, appt_id)
        entry_id = outbox.all_entries[0].id

        for _ in range(MAX_ATTEMPTS):
            dispatcher.run_once()

        assert outbox.get_status(entry_id) == "FAILED"
        assert outbox.get_attempts(entry_id) == MAX_ATTEMPTS

        # One more run: nothing to process.
        count = dispatcher.run_once()
        assert count == 0
        # attempts must not increase beyond the cap.
        assert outbox.get_attempts(entry_id) == MAX_ATTEMPTS

    def test_on_calendar_error_callback_called_with_technician_id_and_exception(
        self,
        appt_repo: InMemoryAppointmentRepository,
        outbox: InMemoryOutboxRepository,
        uow: FakeUnitOfWork,
    ):
        """When create_event raises, the injected on_calendar_error callback is invoked
        with the appointment's technician_id and the raised exception. The existing
        mark_failed / retry behavior is unchanged."""

        raised_exc = RuntimeError("auth revoked")

        class ErrorCalendar:
            def create_event(self, appt, context):
                raise raised_exc

            def update_event(self, eid, appt, context):
                pass

            def delete_event(self, eid):
                pass

        callback_calls: list[tuple] = []

        def on_error(technician_id, exc):
            callback_calls.append((technician_id, exc))

        appt_id = UUID("aaaaaaaa-0000-0000-0000-000000000030")
        appt_repo.add(_make_appointment(appt_id))
        outbox.enqueue(OutboxOperation.CREATE, appt_id)
        entry_id = outbox.all_entries[0].id

        dispatcher = CalendarProjectionDispatcher(
            uow_factory=lambda: uow,
            calendar=ErrorCalendar(),
            on_calendar_error=on_error,
        )
        count = dispatcher.run_once(limit=1)

        # Existing retry behavior: count is 0, entry is still PENDING with 1 attempt.
        assert count == 0
        assert outbox.get_status(entry_id) == "PENDING"
        assert outbox.get_attempts(entry_id) == 1

        # Callback invoked exactly once with the correct technician_id and exception.
        assert len(callback_calls) == 1
        called_tech_id, called_exc = callback_calls[0]
        assert called_tech_id == _TECH_ID
        assert called_exc is raised_exc

    def test_on_calendar_error_callback_exception_does_not_escape(
        self,
        appt_repo: InMemoryAppointmentRepository,
        outbox: InMemoryOutboxRepository,
        uow: FakeUnitOfWork,
    ):
        """A failing on_calendar_error callback must not propagate — retry semantics are preserved."""

        class ErrorCalendar:
            def create_event(self, appt, context):
                raise RuntimeError("calendar error")

            def update_event(self, eid, appt, context):
                pass

            def delete_event(self, eid):
                pass

        def bad_callback(technician_id, exc):
            raise ValueError("callback exploded")

        appt_id = UUID("aaaaaaaa-0000-0000-0000-000000000031")
        appt_repo.add(_make_appointment(appt_id))
        outbox.enqueue(OutboxOperation.CREATE, appt_id)
        entry_id = outbox.all_entries[0].id

        dispatcher = CalendarProjectionDispatcher(
            uow_factory=lambda: uow,
            calendar=ErrorCalendar(),
            on_calendar_error=bad_callback,
        )
        # Must not raise even though the callback raises.
        count = dispatcher.run_once(limit=1)
        assert count == 0
        assert outbox.get_status(entry_id) == "PENDING"


class TestPerTechnicianRouting:
    """Verify that CalendarProjectionDispatcher routes each entry to the calendar
    that belongs to the entry's appointment owner."""

    _TECH_A = UUID("aaaaaaaa-1111-0000-0000-000000000001")
    _TECH_B = UUID("bbbbbbbb-1111-0000-0000-000000000001")

    def _make_appt(self, appt_id: UUID, technician_id: UUID) -> "Appointment":
        return Appointment(
            id=appt_id,
            service_call_id=_SC_ID,
            technician_id=technician_id,
            customer_id=_CUST_ID,
            time_range=TimeRange(
                start=datetime(2024, 6, 10, 9, 0, tzinfo=_TZ),
                end=datetime(2024, 6, 10, 11, 0, tzinfo=_TZ),
            ),
            status=AppointmentStatus.SCHEDULED,
            details=None,
            external_event_id=None,
            created_at=_NOW,
            updated_at=_NOW,
        )

    def test_each_technician_receives_only_their_own_event(self):
        appt_repo = InMemoryAppointmentRepository()
        outbox = InMemoryOutboxRepository()
        sc_repo = InMemoryServiceCallRepository()
        sc_repo.add(
            ServiceCall(
                id=_SC_ID,
                customer_id=_CUST_ID,
                description=_PROBLEM,
                status=ServiceCallStatus.SCHEDULED,
                created_at=_NOW,
            )
        )
        uow = FakeUnitOfWork(outbox=outbox, appointments=appt_repo, service_calls=sc_repo)

        cal_a = FakeCalendarPort()
        cal_b = FakeCalendarPort()

        def resolver(technician_id):
            return {self._TECH_A: cal_a, self._TECH_B: cal_b}[technician_id]

        dispatcher = CalendarProjectionDispatcher(
            uow_factory=lambda: uow,
            calendar_resolver=resolver,
        )

        appt_a_id = UUID("aaaaaaaa-0000-0000-0000-000000000020")
        appt_b_id = UUID("aaaaaaaa-0000-0000-0000-000000000021")
        appt_repo.add(self._make_appt(appt_a_id, self._TECH_A))
        appt_repo.add(self._make_appt(appt_b_id, self._TECH_B))
        outbox.enqueue(OutboxOperation.CREATE, appt_a_id)
        outbox.enqueue(OutboxOperation.CREATE, appt_b_id)

        count = dispatcher.run_once()

        assert count == 2
        assert len(cal_a.created_events) == 1
        assert len(cal_b.created_events) == 1
        # A's calendar only received A's appointment; B's calendar only B's.
        (a_appt,) = cal_a.created_events.values()
        (b_appt,) = cal_b.created_events.values()
        assert a_appt.id == appt_a_id
        assert b_appt.id == appt_b_id

    def test_raises_when_neither_calendar_nor_resolver_given(self):
        with pytest.raises(ValueError):
            CalendarProjectionDispatcher(uow_factory=lambda: None)

    def test_raises_when_both_calendar_and_resolver_given(self):
        with pytest.raises(ValueError):
            CalendarProjectionDispatcher(
                uow_factory=lambda: None,
                calendar=FakeCalendarPort(),
                calendar_resolver=lambda _: FakeCalendarPort(),
            )


class TestContextEnrichment:
    def test_create_passes_customer_name_and_problem_to_calendar(
        self,
        dispatcher: CalendarProjectionDispatcher,
        appt_repo: InMemoryAppointmentRepository,
        outbox: InMemoryOutboxRepository,
        calendar: FakeCalendarPort,
    ) -> None:
        appt_id = UUID("aaaaaaaa-0000-0000-0000-000000000010")
        appt_repo.add(_make_appointment(appt_id))
        outbox.enqueue(OutboxOperation.CREATE, appt_id)

        dispatcher.run_once()

        [context] = calendar.created_contexts.values()
        assert context.customer_name == _CUSTOMER_NAME
        assert context.problem_description == _PROBLEM

    def test_update_passes_customer_name_and_problem_to_calendar(
        self,
        dispatcher: CalendarProjectionDispatcher,
        appt_repo: InMemoryAppointmentRepository,
        outbox: InMemoryOutboxRepository,
        calendar: FakeCalendarPort,
    ) -> None:
        appt_id = UUID("aaaaaaaa-0000-0000-0000-000000000040")
        appt_repo.add(_make_appointment(appt_id, external_event_id="evt-existing"))
        outbox.enqueue(OutboxOperation.UPDATE, appt_id)

        dispatcher.run_once()

        context = calendar.updated_contexts["evt-existing"]
        assert context.customer_name == _CUSTOMER_NAME
        assert context.problem_description == _PROBLEM
