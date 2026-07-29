"""Integration tests for the scheduling persistence layer against real Postgres.

A Postgres 16 container is started once per module via testcontainers. The
real Alembic migration is applied (including the btree_gist extension and the
GiST exclusion constraint), then each test runs inside its own transaction that
is rolled back on teardown, keeping tests isolated without re-migrating.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from testcontainers.postgres import PostgresContainer

from fsm.scheduling.adapters.outbox_repository import SqlAlchemyOutboxRepository
from fsm.scheduling.adapters.repositories import (
    SqlAlchemyAppointmentRepository,
    SqlAlchemyServiceCallRepository,
)
from fsm.scheduling.adapters.unit_of_work import SqlAlchemyUnitOfWork
from fsm.scheduling.application.calendar_projection_dispatcher import CalendarProjectionDispatcher
from fsm.scheduling.domain.appointment import Appointment, AppointmentStatus
from fsm.scheduling.domain.errors import NotFoundError, SlotUnavailable
from fsm.scheduling.domain.service_call import ServiceCall, ServiceCallStatus
from fsm.scheduling.domain.time_range import TimeRange
from fsm.scheduling.ports.outbox import OutboxOperation
from tests.scheduling.fakes import FakeCalendarPort


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utc(year: int, month: int, day: int, hour: int = 0) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


def _make_service_call() -> ServiceCall:
    return ServiceCall(
        id=uuid.uuid4(),
        customer_id=uuid.uuid4(),
        description="Fix boiler",
        status=ServiceCallStatus.OPEN,
        created_at=_utc(2024, 1, 1),
    )


def _make_appointment(
    *,
    technician_id: uuid.UUID | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    status: AppointmentStatus = AppointmentStatus.SCHEDULED,
) -> Appointment:
    if technician_id is None:
        technician_id = uuid.uuid4()
    if start is None:
        start = _utc(2024, 6, 1, 9)
    if end is None:
        end = _utc(2024, 6, 1, 11)
    return Appointment(
        id=uuid.uuid4(),
        service_call_id=uuid.uuid4(),
        technician_id=technician_id,
        customer_id=uuid.uuid4(),
        time_range=TimeRange(start=start, end=end),
        status=status,
        details=None,
        external_event_id=None,
        created_at=_utc(2024, 1, 1),
        updated_at=_utc(2024, 1, 1),
    )


# ---------------------------------------------------------------------------
# Module-scoped container + migrated engine
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def pg_engine():
    """Start a Postgres 16 container, run migrations, yield an engine."""
    with PostgresContainer("pgvector/pgvector:pg16", driver="psycopg") as pg:
        url = pg.get_connection_url()
        os.environ["DATABASE_URL"] = url

        cfg = AlembicConfig()
        cfg.set_main_option(
            "script_location",
            str(__import__("pathlib").Path(__file__).parents[3] / "alembic"),
        )
        cfg.set_main_option("sqlalchemy.url", url)
        alembic_command.upgrade(cfg, "head")

        engine = create_engine(url)
        yield engine
        engine.dispose()

        del os.environ["DATABASE_URL"]


@pytest.fixture
def session(pg_engine):
    """Yield a session inside a savepoint; roll back after each test."""
    Session = sessionmaker(bind=pg_engine, expire_on_commit=False)
    with Session() as sess:
        with sess.begin():
            # Nested savepoint so individual tests can call flush() without
            # committing; the outer transaction rolls back after each test.
            sess.begin_nested()
            yield sess
            sess.rollback()


# ---------------------------------------------------------------------------
# GiST exclusion-constraint assertions
# ---------------------------------------------------------------------------

class TestExclusionConstraint:
    def test_overlapping_appointment_same_technician_raises_integrity_error(self, session):
        """The EXCLUDE constraint prevents two non-cancelled overlapping appointments."""
        tech = uuid.uuid4()
        appt1 = _make_appointment(technician_id=tech, start=_utc(2024, 6, 1, 9), end=_utc(2024, 6, 1, 11))
        appt2 = _make_appointment(technician_id=tech, start=_utc(2024, 6, 1, 10), end=_utc(2024, 6, 1, 12))

        from fsm.scheduling.adapters.orm import AppointmentRow
        session.add(AppointmentRow(
            id=appt1.id,
            service_call_id=appt1.service_call_id,
            technician_id=appt1.technician_id,
            customer_id=appt1.customer_id,
            start_at=appt1.time_range.start,
            end_at=appt1.time_range.end,
            status=appt1.status.value,
            details=None,
            external_event_id=None,
            created_at=appt1.created_at,
            updated_at=appt1.updated_at,
        ))
        session.flush()

        session.add(AppointmentRow(
            id=appt2.id,
            service_call_id=appt2.service_call_id,
            technician_id=appt2.technician_id,
            customer_id=appt2.customer_id,
            start_at=appt2.time_range.start,
            end_at=appt2.time_range.end,
            status=appt2.status.value,
            details=None,
            external_event_id=None,
            created_at=appt2.created_at,
            updated_at=appt2.updated_at,
        ))
        with pytest.raises(IntegrityError):
            session.flush()

    def test_adjacent_appointments_same_technician_allowed(self, session):
        """Adjacent time slots (end of one == start of next) are NOT overlapping under [start, end)."""
        tech = uuid.uuid4()
        appt1 = _make_appointment(technician_id=tech, start=_utc(2024, 6, 1, 9), end=_utc(2024, 6, 1, 11))
        appt2 = _make_appointment(technician_id=tech, start=_utc(2024, 6, 1, 11), end=_utc(2024, 6, 1, 13))

        from fsm.scheduling.adapters.orm import AppointmentRow
        for appt in (appt1, appt2):
            session.add(AppointmentRow(
                id=appt.id,
                service_call_id=appt.service_call_id,
                technician_id=appt.technician_id,
                customer_id=appt.customer_id,
                start_at=appt.time_range.start,
                end_at=appt.time_range.end,
                status=appt.status.value,
                details=None,
                external_event_id=None,
                created_at=appt.created_at,
                updated_at=appt.updated_at,
            ))
        # Must not raise.
        session.flush()

    def test_overlapping_appointment_different_technician_allowed(self, session):
        """The EXCLUDE constraint is per-technician; different technicians may overlap."""
        tech_a = uuid.uuid4()
        tech_b = uuid.uuid4()
        appt1 = _make_appointment(technician_id=tech_a, start=_utc(2024, 6, 1, 9), end=_utc(2024, 6, 1, 11))
        appt2 = _make_appointment(technician_id=tech_b, start=_utc(2024, 6, 1, 9), end=_utc(2024, 6, 1, 11))

        from fsm.scheduling.adapters.orm import AppointmentRow
        for appt in (appt1, appt2):
            session.add(AppointmentRow(
                id=appt.id,
                service_call_id=appt.service_call_id,
                technician_id=appt.technician_id,
                customer_id=appt.customer_id,
                start_at=appt.time_range.start,
                end_at=appt.time_range.end,
                status=appt.status.value,
                details=None,
                external_event_id=None,
                created_at=appt.created_at,
                updated_at=appt.updated_at,
            ))
        session.flush()  # Must not raise.

    def test_overlapping_cancelled_appointment_allowed(self, session):
        """The WHERE clause (status <> 'cancelled') exempts cancelled appointments from the constraint."""
        tech = uuid.uuid4()
        appt_active = _make_appointment(
            technician_id=tech,
            start=_utc(2024, 6, 1, 9),
            end=_utc(2024, 6, 1, 11),
            status=AppointmentStatus.SCHEDULED,
        )
        appt_cancelled = _make_appointment(
            technician_id=tech,
            start=_utc(2024, 6, 1, 9),
            end=_utc(2024, 6, 1, 11),
            status=AppointmentStatus.CANCELLED,
        )

        from fsm.scheduling.adapters.orm import AppointmentRow
        for appt in (appt_active, appt_cancelled):
            session.add(AppointmentRow(
                id=appt.id,
                service_call_id=appt.service_call_id,
                technician_id=appt.technician_id,
                customer_id=appt.customer_id,
                start_at=appt.time_range.start,
                end_at=appt.time_range.end,
                status=appt.status.value,
                details=None,
                external_event_id=None,
                created_at=appt.created_at,
                updated_at=appt.updated_at,
            ))
        session.flush()  # Must not raise.


# ---------------------------------------------------------------------------
# Repository contract tests against real Postgres
# ---------------------------------------------------------------------------

class TestSqlAlchemyServiceCallRepository:
    def test_add_then_get_round_trips(self, session):
        repo = SqlAlchemyServiceCallRepository(session)
        sc = _make_service_call()
        repo.add(sc)
        fetched = repo.get(sc.id)
        assert fetched.id == sc.id
        assert fetched.customer_id == sc.customer_id
        assert fetched.description == sc.description
        assert fetched.status == sc.status

    def test_get_missing_raises_not_found(self, session):
        repo = SqlAlchemyServiceCallRepository(session)
        with pytest.raises(NotFoundError):
            repo.get(uuid.uuid4())

    def test_save_persists_status_mutation(self, session):
        repo = SqlAlchemyServiceCallRepository(session)
        sc = _make_service_call()
        repo.add(sc)
        sc.mark_scheduled()
        repo.save(sc)
        fetched = repo.get(sc.id)
        assert fetched.status == ServiceCallStatus.SCHEDULED


class TestSqlAlchemyAppointmentRepository:
    def test_add_then_get_round_trips(self, session):
        repo = SqlAlchemyAppointmentRepository(session)
        appt = _make_appointment()
        repo.add(appt)
        fetched = repo.get(appt.id)
        assert fetched.id == appt.id
        assert fetched.technician_id == appt.technician_id
        assert fetched.time_range == appt.time_range
        assert fetched.status == appt.status

    def test_get_missing_raises_not_found(self, session):
        repo = SqlAlchemyAppointmentRepository(session)
        with pytest.raises(NotFoundError):
            repo.get(uuid.uuid4())

    def test_save_persists_status_and_time_mutation(self, session):
        repo = SqlAlchemyAppointmentRepository(session)
        appt = _make_appointment()
        repo.add(appt)
        new_range = TimeRange(start=_utc(2024, 6, 2, 9), end=_utc(2024, 6, 2, 11))
        appt.reschedule(new_range, now=_utc(2024, 6, 2, 8))
        repo.save(appt)
        fetched = repo.get(appt.id)
        assert fetched.status == AppointmentStatus.RESCHEDULED
        assert fetched.time_range == new_range

    # list_for_technician_between -------------------------------------------

    def test_list_returns_overlapping_appointment(self, session):
        repo = SqlAlchemyAppointmentRepository(session)
        tech = uuid.uuid4()
        appt = _make_appointment(technician_id=tech, start=_utc(2024, 6, 1, 9), end=_utc(2024, 6, 1, 11))
        repo.add(appt)
        result = repo.list_for_technician_between(tech, _utc(2024, 6, 1, 8), _utc(2024, 6, 1, 10))
        assert any(a.id == appt.id for a in result)

    def test_list_excludes_non_overlapping(self, session):
        repo = SqlAlchemyAppointmentRepository(session)
        tech = uuid.uuid4()
        appt = _make_appointment(technician_id=tech, start=_utc(2024, 6, 1, 14), end=_utc(2024, 6, 1, 16))
        repo.add(appt)
        result = repo.list_for_technician_between(tech, _utc(2024, 6, 1, 8), _utc(2024, 6, 1, 12))
        assert not any(a.id == appt.id for a in result)

    def test_list_excludes_cancelled(self, session):
        repo = SqlAlchemyAppointmentRepository(session)
        tech = uuid.uuid4()
        appt = _make_appointment(
            technician_id=tech,
            start=_utc(2024, 6, 1, 9),
            end=_utc(2024, 6, 1, 11),
            status=AppointmentStatus.CANCELLED,
        )
        repo.add(appt)
        result = repo.list_for_technician_between(tech, _utc(2024, 6, 1, 8), _utc(2024, 6, 1, 12))
        assert not any(a.id == appt.id for a in result)

    def test_list_excludes_other_technician(self, session):
        repo = SqlAlchemyAppointmentRepository(session)
        tech_a = uuid.uuid4()
        tech_b = uuid.uuid4()
        appt = _make_appointment(technician_id=tech_b, start=_utc(2024, 6, 1, 9), end=_utc(2024, 6, 1, 11))
        repo.add(appt)
        result = repo.list_for_technician_between(tech_a, _utc(2024, 6, 1, 8), _utc(2024, 6, 1, 12))
        assert not any(a.id == appt.id for a in result)

    def test_list_includes_rescheduled_appointment(self, session):
        repo = SqlAlchemyAppointmentRepository(session)
        tech = uuid.uuid4()
        appt = _make_appointment(
            technician_id=tech,
            start=_utc(2024, 6, 1, 9),
            end=_utc(2024, 6, 1, 11),
            status=AppointmentStatus.RESCHEDULED,
        )
        repo.add(appt)
        result = repo.list_for_technician_between(tech, _utc(2024, 6, 1, 8), _utc(2024, 6, 1, 12))
        assert any(a.id == appt.id for a in result)

    # Half-open boundary contract -------------------------------------------

    def test_appointment_ending_exactly_at_window_start_is_excluded(self, session):
        """Appointment [09:00, 11:00) ending at window start 11:00 is NOT in the result."""
        repo = SqlAlchemyAppointmentRepository(session)
        tech = uuid.uuid4()
        appt = _make_appointment(technician_id=tech, start=_utc(2024, 6, 1, 9), end=_utc(2024, 6, 1, 11))
        repo.add(appt)
        result = repo.list_for_technician_between(tech, _utc(2024, 6, 1, 11), _utc(2024, 6, 1, 13))
        assert not any(a.id == appt.id for a in result)

    def test_appointment_starting_exactly_at_window_end_is_excluded(self, session):
        """Appointment [13:00, 15:00) starting at window end 13:00 is NOT in the result."""
        repo = SqlAlchemyAppointmentRepository(session)
        tech = uuid.uuid4()
        appt = _make_appointment(technician_id=tech, start=_utc(2024, 6, 1, 13), end=_utc(2024, 6, 1, 15))
        repo.add(appt)
        result = repo.list_for_technician_between(tech, _utc(2024, 6, 1, 9), _utc(2024, 6, 1, 13))
        assert not any(a.id == appt.id for a in result)

    def test_appointment_overlapping_by_positive_duration_is_included(self, session):
        """Appointment [10:00, 12:00) overlaps window [11:00, 13:00) by one hour."""
        repo = SqlAlchemyAppointmentRepository(session)
        tech = uuid.uuid4()
        appt = _make_appointment(technician_id=tech, start=_utc(2024, 6, 1, 10), end=_utc(2024, 6, 1, 12))
        repo.add(appt)
        result = repo.list_for_technician_between(tech, _utc(2024, 6, 1, 11), _utc(2024, 6, 1, 13))
        assert any(a.id == appt.id for a in result)

    def test_overlapping_add_raises_slot_unavailable_not_integrity_error(self, session):
        """Repository.add translates the overlap IntegrityError into SlotUnavailable.

        The raw IntegrityError must not escape the repository boundary; only the
        domain SlotUnavailable is visible to callers.
        """
        repo = SqlAlchemyAppointmentRepository(session)
        tech = uuid.uuid4()
        appt1 = _make_appointment(technician_id=tech, start=_utc(2024, 6, 1, 9), end=_utc(2024, 6, 1, 11))
        appt2 = _make_appointment(technician_id=tech, start=_utc(2024, 6, 1, 10), end=_utc(2024, 6, 1, 12))
        repo.add(appt1)
        with pytest.raises(SlotUnavailable):
            repo.add(appt2)


# ---------------------------------------------------------------------------
# Unit-of-Work transaction boundary tests
# ---------------------------------------------------------------------------

@pytest.fixture
def session_factory(pg_engine):
    return sessionmaker(bind=pg_engine, expire_on_commit=False)


class TestSqlAlchemyUnitOfWork:
    def test_commit_persists_both_entities(self, session_factory):
        """Committing a UoW persists an appointment and service call atomically."""
        sc = _make_service_call()
        appt = _make_appointment()

        with SqlAlchemyUnitOfWork(session_factory) as uow:
            uow.service_calls.add(sc)
            uow.appointments.add(appt)
            uow.commit()

        # Verify with a fresh session that both rows exist
        with sessionmaker(bind=session_factory.kw["bind"])() as verify_session:
            sc_repo = SqlAlchemyServiceCallRepository(verify_session)
            appt_repo = SqlAlchemyAppointmentRepository(verify_session)
            assert sc_repo.get(sc.id).id == sc.id
            assert appt_repo.get(appt.id).id == appt.id

    def test_exception_before_commit_rolls_back(self, session_factory):
        """Raising inside the with-block before commit rolls back all changes."""
        sc = _make_service_call()
        appt = _make_appointment()

        with pytest.raises(RuntimeError, match="intentional rollback"):
            with SqlAlchemyUnitOfWork(session_factory) as uow:
                uow.service_calls.add(sc)
                uow.appointments.add(appt)
                raise RuntimeError("intentional rollback")

        # Verify with a fresh session that NOTHING was persisted
        with sessionmaker(bind=session_factory.kw["bind"])() as verify_session:
            sc_repo = SqlAlchemyServiceCallRepository(verify_session)
            appt_repo = SqlAlchemyAppointmentRepository(verify_session)
            with pytest.raises(NotFoundError):
                sc_repo.get(sc.id)
            with pytest.raises(NotFoundError):
                appt_repo.get(appt.id)

    def test_uow_exposes_outbox_repo(self, session_factory):
        """UnitOfWork exposes an outbox repository sharing the same transaction."""
        appt = _make_appointment()

        with SqlAlchemyUnitOfWork(session_factory) as uow:
            uow.appointments.add(appt)
            uow.outbox.enqueue(OutboxOperation.CREATE, appt.id)
            uow.commit()

        with sessionmaker(bind=session_factory.kw["bind"])() as verify_session:
            outbox_repo = SqlAlchemyOutboxRepository(verify_session)
            pending = outbox_repo.list_pending(limit=10)
            assert any(e.appointment_id == appt.id for e in pending)


# ---------------------------------------------------------------------------
# Outbox repository + dispatcher integration tests (real PG)
# ---------------------------------------------------------------------------


class TestSqlAlchemyOutboxRepository:
    def test_enqueue_creates_pending_row(self, session):
        repo = SqlAlchemyOutboxRepository(session)
        appt_id = uuid.uuid4()
        repo.enqueue(OutboxOperation.CREATE, appt_id)
        pending = repo.list_pending(limit=10)
        assert any(e.appointment_id == appt_id for e in pending)

    def test_list_pending_is_fifo(self, session):
        repo = SqlAlchemyOutboxRepository(session)
        ids = [uuid.uuid4() for _ in range(3)]
        for appt_id in ids:
            repo.enqueue(OutboxOperation.CREATE, appt_id)
        pending = repo.list_pending(limit=10)
        fetched_ids = [e.appointment_id for e in pending if e.appointment_id in ids]
        assert fetched_ids == ids

    def test_mark_processed_removes_from_pending(self, session):
        repo = SqlAlchemyOutboxRepository(session)
        appt_id = uuid.uuid4()
        repo.enqueue(OutboxOperation.CREATE, appt_id)
        entry = next(e for e in repo.list_pending(10) if e.appointment_id == appt_id)
        repo.mark_processed(entry.id)
        pending = repo.list_pending(limit=10)
        assert not any(e.appointment_id == appt_id for e in pending)

    def test_mark_failed_keeps_pending_below_cap(self, session):
        """mark_failed keeps the entry PENDING while attempts < MAX_ATTEMPTS (retryable)."""
        repo = SqlAlchemyOutboxRepository(session)
        appt_id = uuid.uuid4()
        repo.enqueue(OutboxOperation.CREATE, appt_id)
        entry = next(e for e in repo.list_pending(10) if e.appointment_id == appt_id)
        # One failure: still below cap, must remain PENDING.
        repo.mark_failed(entry.id, "calendar down")
        pending = repo.list_pending(limit=10)
        assert any(e.appointment_id == appt_id for e in pending)

    def test_mark_failed_dead_letters_at_cap(self, session):
        """mark_failed sets FAILED (dead-letter) once attempts reaches MAX_ATTEMPTS."""
        from fsm.scheduling.ports.outbox import MAX_ATTEMPTS
        repo = SqlAlchemyOutboxRepository(session)
        appt_id = uuid.uuid4()
        repo.enqueue(OutboxOperation.CREATE, appt_id)
        entry = next(e for e in repo.list_pending(10) if e.appointment_id == appt_id)
        for i in range(MAX_ATTEMPTS):
            # Re-fetch entry id each time since list_pending includes updated attempts.
            entry = next(e for e in repo.list_pending(10) if e.appointment_id == appt_id)
            repo.mark_failed(entry.id, f"error {i}")
        pending = repo.list_pending(limit=10)
        assert not any(e.appointment_id == appt_id for e in pending)

    def test_enqueue_with_external_event_id(self, session):
        repo = SqlAlchemyOutboxRepository(session)
        appt_id = uuid.uuid4()
        repo.enqueue(OutboxOperation.DELETE, appt_id, external_event_id="evt-xyz")
        pending = repo.list_pending(limit=10)
        entry = next(e for e in pending if e.appointment_id == appt_id)
        assert entry.external_event_id == "evt-xyz"


class TestOutboxDispatcherIntegration:
    def test_booking_writes_and_dispatcher_run_are_atomic_and_correct(
        self, session_factory
    ):
        """Full end-to-end: booking writes appointment + outbox entry atomically (UoW).
        Then dispatcher.run_once() with per-entry transactions sets external_event_id
        and marks the outbox entry PROCESSED.
        """
        appt = _make_appointment()
        sc = ServiceCall(
            id=appt.service_call_id,
            customer_id=appt.customer_id,
            description="Fix boiler",
            status=ServiceCallStatus.OPEN,
            created_at=_utc(2024, 1, 1),
        )

        with SqlAlchemyUnitOfWork(session_factory) as uow:
            uow.service_calls.add(sc)
            uow.appointments.add(appt)
            uow.outbox.enqueue(OutboxOperation.CREATE, appt.id)
            uow.commit()

        fake_calendar = FakeCalendarPort()

        dispatcher = CalendarProjectionDispatcher(
            uow_factory=lambda: SqlAlchemyUnitOfWork(session_factory),
            calendar=fake_calendar,
        )
        # Use a large limit since other tests in this module may have left PENDING entries.
        dispatcher.run_once(limit=200)

        engine = session_factory.kw["bind"]
        Session = sessionmaker(bind=engine, expire_on_commit=False)

        # Our appointment's external_event_id must be set
        with Session() as verify_sess:
            fetched = SqlAlchemyAppointmentRepository(verify_sess).get(appt.id)
            assert fetched.external_event_id is not None
            assert fetched.external_event_id in fake_calendar.created_events

        # Our outbox entry must be PROCESSED (not in pending list)
        with Session() as verify_sess:
            outbox_repo = SqlAlchemyOutboxRepository(verify_sess)
            pending = outbox_repo.list_pending(limit=200)
            assert not any(e.appointment_id == appt.id for e in pending)

    def test_rollback_removes_both_appointment_and_outbox_entry(self, session_factory):
        """An exception before commit rolls back both the appointment and outbox rows."""
        appt = _make_appointment()

        with pytest.raises(RuntimeError):
            with SqlAlchemyUnitOfWork(session_factory) as uow:
                uow.appointments.add(appt)
                uow.outbox.enqueue(OutboxOperation.CREATE, appt.id)
                raise RuntimeError("rollback test")

        engine = session_factory.kw["bind"]
        with sessionmaker(bind=engine, expire_on_commit=False)() as verify_sess:
            with pytest.raises(NotFoundError):
                SqlAlchemyAppointmentRepository(verify_sess).get(appt.id)
            pending = SqlAlchemyOutboxRepository(verify_sess).list_pending(limit=10)
            assert not any(e.appointment_id == appt.id for e in pending)

    def test_claim_next_skip_locked_two_sequential_claims_return_different_rows(
        self, session_factory
    ):
        """Two sequential claim_next calls in separate transactions return different rows.

        True parallel dispatch is hard to test reliably; this test verifies the FIFO
        single-caller contract. The SKIP LOCKED guarantee (concurrent dispatchers never
        share a row) is verified by the PostgreSQL lock semantics inherent in
        .with_for_update(skip_locked=True) — a second transaction cannot claim a row
        held by an open first transaction.
        """
        engine = session_factory.kw["bind"]
        Session = sessionmaker(bind=engine, expire_on_commit=False)

        appt_a = _make_appointment()
        appt_b = _make_appointment()

        # Enqueue two entries.
        with SqlAlchemyUnitOfWork(session_factory) as uow:
            uow.appointments.add(appt_a)
            uow.appointments.add(appt_b)
            uow.outbox.enqueue(OutboxOperation.CREATE, appt_a.id)
            uow.outbox.enqueue(OutboxOperation.CREATE, appt_b.id)
            uow.commit()

        # Two sequential claim_next calls in separate transactions return distinct entries.
        with Session() as sess_a:
            with sess_a.begin():
                repo_a = SqlAlchemyOutboxRepository(sess_a)
                entry_a = repo_a.claim_next()
                assert entry_a is not None

                with Session() as sess_b:
                    with sess_b.begin():
                        repo_b = SqlAlchemyOutboxRepository(sess_b)
                        entry_b = repo_b.claim_next()
                        assert entry_b is not None
                        # SKIP LOCKED: sess_b skips the locked entry_a and claims entry_b.
                        assert entry_a.id != entry_b.id

    def test_mark_processed_raises_for_missing_entry(self, session_factory):
        """mark_processed raises NotFoundError when the entry id is absent."""
        with SqlAlchemyUnitOfWork(session_factory) as uow:
            with pytest.raises(NotFoundError):
                uow.outbox.mark_processed(uuid.uuid4())

    def test_mark_failed_raises_for_missing_entry(self, session_factory):
        """mark_failed raises NotFoundError when the entry id is absent."""
        with SqlAlchemyUnitOfWork(session_factory) as uow:
            with pytest.raises(NotFoundError):
                uow.outbox.mark_failed(uuid.uuid4(), "no such entry")

    def test_mark_failed_retries_until_cap_then_dead_letters(self, session_factory):
        """mark_failed keeps status PENDING while attempts < MAX_ATTEMPTS; at the cap it sets FAILED."""
        from fsm.scheduling.ports.outbox import MAX_ATTEMPTS

        appt = _make_appointment()

        with SqlAlchemyUnitOfWork(session_factory) as uow:
            uow.appointments.add(appt)
            uow.outbox.enqueue(OutboxOperation.CREATE, appt.id)
            uow.commit()

        engine = session_factory.kw["bind"]
        Session = sessionmaker(bind=engine, expire_on_commit=False)

        # Retrieve the entry id.
        with Session() as sess:
            repo = SqlAlchemyOutboxRepository(sess)
            entries = repo.list_pending(limit=10)
            entry = next(e for e in entries if e.appointment_id == appt.id)
            entry_id = entry.id

        # Call mark_failed MAX_ATTEMPTS - 1 times; entry must stay PENDING each time.
        for i in range(MAX_ATTEMPTS - 1):
            with SqlAlchemyUnitOfWork(session_factory) as uow:
                uow.outbox.mark_failed(entry_id, f"error {i}")
                uow.commit()
            with Session() as sess:
                pending = SqlAlchemyOutboxRepository(sess).list_pending(limit=10)
                assert any(e.id == entry_id for e in pending), f"entry must still be PENDING after {i+1} failures"

        # Final call: hits the cap → dead-letter.
        with SqlAlchemyUnitOfWork(session_factory) as uow:
            uow.outbox.mark_failed(entry_id, "final error")
            uow.commit()

        with Session() as sess:
            pending = SqlAlchemyOutboxRepository(sess).list_pending(limit=10)
            assert not any(e.id == entry_id for e in pending), "dead-lettered entry must not appear in pending"


# ---------------------------------------------------------------------------
# Upcoming-appointment queries
# ---------------------------------------------------------------------------


class TestUpcomingQueries:
    def _persist(self, session, *, technician_id, customer_id, start, end, status=AppointmentStatus.SCHEDULED):
        sc_repo = SqlAlchemyServiceCallRepository(session)
        appt_repo = SqlAlchemyAppointmentRepository(session)
        sc = _make_service_call()
        sc_repo.add(sc)
        appt = Appointment(
            id=uuid.uuid4(),
            service_call_id=sc.id,
            technician_id=technician_id,
            customer_id=customer_id,
            time_range=TimeRange(start=start, end=end),
            status=status,
            details=None,
            external_event_id=None,
            created_at=_utc(2024, 1, 1),
            updated_at=_utc(2024, 1, 1),
        )
        appt_repo.add(appt)
        return appt

    def test_technician_upcoming_orders_filters_and_limits(self, session):
        tech = uuid.uuid4()
        cust = uuid.uuid4()
        now = _utc(2030, 1, 1)
        later = self._persist(session, technician_id=tech, customer_id=cust, start=_utc(2030, 6, 2, 9), end=_utc(2030, 6, 2, 11))
        sooner = self._persist(session, technician_id=tech, customer_id=cust, start=_utc(2030, 6, 1, 9), end=_utc(2030, 6, 1, 11))
        # Excluded: cancelled, already-ended, and another technician's appointment.
        self._persist(session, technician_id=tech, customer_id=cust, start=_utc(2030, 7, 1, 9), end=_utc(2030, 7, 1, 11), status=AppointmentStatus.CANCELLED)
        self._persist(session, technician_id=tech, customer_id=cust, start=_utc(2020, 1, 1, 9), end=_utc(2020, 1, 1, 11))
        self._persist(session, technician_id=uuid.uuid4(), customer_id=cust, start=_utc(2030, 6, 1, 9), end=_utc(2030, 6, 1, 11))

        result = SqlAlchemyAppointmentRepository(session).list_upcoming_for_technician(tech, now, limit=5)

        assert [a.id for a in result] == [sooner.id, later.id]

    def test_upcoming_respects_limit(self, session):
        tech = uuid.uuid4()
        cust = uuid.uuid4()
        now = _utc(2030, 1, 1)
        for day in range(1, 5):
            self._persist(session, technician_id=tech, customer_id=cust, start=_utc(2030, 6, day, 9), end=_utc(2030, 6, day, 11))
        result = SqlAlchemyAppointmentRepository(session).list_upcoming_for_technician(tech, now, limit=2)
        assert len(result) == 2

    def test_customer_and_all_scopes(self, session):
        tech = uuid.uuid4()
        cust = uuid.uuid4()
        now = _utc(2030, 1, 1)
        mine = self._persist(session, technician_id=tech, customer_id=cust, start=_utc(2030, 6, 1, 9), end=_utc(2030, 6, 1, 11))
        self._persist(session, technician_id=tech, customer_id=uuid.uuid4(), start=_utc(2030, 6, 2, 9), end=_utc(2030, 6, 2, 11))

        repo = SqlAlchemyAppointmentRepository(session)
        customer_view = repo.list_upcoming_for_customer(cust, now, limit=10)
        assert [a.id for a in customer_view] == [mine.id]
        assert mine.id in {a.id for a in repo.list_upcoming_all(now, limit=10)}
