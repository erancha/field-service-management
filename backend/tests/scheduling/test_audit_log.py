"""Audit log tests for §8: every appointment transition writes an audit row.

Unit tests use the in-memory fake repository; the integration test uses real Postgres
via testcontainers (same fixture setup as test_persistence.py).
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest

from fsm.scheduling.domain.appointment import (
    Appointment,
    AppointmentStatus,
    AuditAction,
)
from fsm.scheduling.domain.time_range import TimeRange


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utc(hour: int = 0, minute: int = 0) -> datetime:
    return datetime(2024, 6, 1, hour, minute, tzinfo=timezone.utc)


def _range(start_h: int, end_h: int) -> TimeRange:
    return TimeRange(start=_utc(start_h), end=_utc(end_h))


def _make_appointment(**kwargs) -> Appointment:
    defaults = dict(
        id=uuid.uuid4(),
        service_call_id=uuid.uuid4(),
        technician_id=uuid.uuid4(),
        customer_id=uuid.uuid4(),
        time_range=_range(9, 11),
        status=AppointmentStatus.SCHEDULED,
        details=None,
        created_at=_utc(),
        updated_at=_utc(),
    )
    defaults.update(kwargs)
    return Appointment(**defaults)


# ---------------------------------------------------------------------------
# Unit tests (in-memory fakes)
# ---------------------------------------------------------------------------

class TestAuditRecordDomain:
    """Domain-level: pending_audits field and drain_audits helper."""

    def test_new_appointment_has_empty_pending_audits(self):
        appt = _make_appointment()
        assert appt.pending_audits == []

    def test_pending_audits_excluded_from_equality(self):
        shared_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        shared_sc = uuid.UUID("00000000-0000-0000-0000-000000000002")
        shared_tech = uuid.UUID("00000000-0000-0000-0000-000000000003")
        shared_cust = uuid.UUID("00000000-0000-0000-0000-000000000004")
        appt_a = _make_appointment(
            id=shared_id,
            service_call_id=shared_sc,
            technician_id=shared_tech,
            customer_id=shared_cust,
        )
        appt_b = _make_appointment(
            id=shared_id,
            service_call_id=shared_sc,
            technician_id=shared_tech,
            customer_id=shared_cust,
        )
        appt_a.record_booked(_utc())
        # Despite different pending_audits, equality holds (compare=False on field).
        assert appt_a == appt_b

    def test_record_booked_adds_booked_audit(self):
        appt = _make_appointment()
        now = _utc(8)
        appt.record_booked(now)
        assert len(appt.pending_audits) == 1
        assert appt.pending_audits[0].action == AuditAction.BOOKED
        assert appt.pending_audits[0].occurred_at == now

    def test_reschedule_adds_rescheduled_audit(self):
        appt = _make_appointment()
        now = _utc(9)
        appt.reschedule(_range(12, 14), now=now)
        assert len(appt.pending_audits) == 1
        assert appt.pending_audits[0].action == AuditAction.RESCHEDULED
        assert appt.pending_audits[0].occurred_at == now

    def test_cancel_adds_cancelled_audit(self):
        appt = _make_appointment()
        now = _utc(10)
        appt.cancel(now=now)
        assert len(appt.pending_audits) == 1
        assert appt.pending_audits[0].action == AuditAction.CANCELLED
        assert appt.pending_audits[0].occurred_at == now

    def test_add_details_adds_details_added_audit(self):
        appt = _make_appointment()
        now = _utc(11)
        appt.add_details("Some notes", now=now)
        assert len(appt.pending_audits) == 1
        assert appt.pending_audits[0].action == AuditAction.DETAILS_ADDED
        assert appt.pending_audits[0].occurred_at == now

    def test_assign_external_event_writes_no_audit(self):
        appt = _make_appointment()
        appt.assign_external_event("evt-42")
        assert appt.pending_audits == []

    def test_constructor_has_no_audit(self):
        """Loading via _row_to_appointment (constructor path) must not produce audits."""
        appt = _make_appointment()
        assert appt.pending_audits == []

    def test_drain_audits_returns_and_clears(self):
        appt = _make_appointment()
        now = _utc(8)
        appt.record_booked(now)
        drained = appt.drain_audits()
        assert len(drained) == 1
        assert drained[0].action == AuditAction.BOOKED
        assert appt.pending_audits == []

    def test_multiple_mutations_accumulate_in_order(self):
        appt = _make_appointment()
        t1 = _utc(8)
        t2 = _utc(9)
        t3 = _utc(10)
        appt.record_booked(t1)
        appt.reschedule(_range(12, 14), now=t2)
        appt.add_details("Detail", now=t3)
        assert [r.action for r in appt.pending_audits] == [
            AuditAction.BOOKED,
            AuditAction.RESCHEDULED,
            AuditAction.DETAILS_ADDED,
        ]


class TestInMemoryAuditDrain:
    """InMemoryAppointmentRepository.audits is populated on add/save."""

    def test_book_writes_one_booked_audit(self):
        from tests.scheduling.fakes import InMemoryAppointmentRepository
        repo = InMemoryAppointmentRepository()
        appt = _make_appointment()
        now = _utc(8)
        appt.record_booked(now)
        repo.add(appt)
        assert len(repo.audits) == 1
        appt_id, action, occurred_at = repo.audits[0]
        assert appt_id == appt.id
        assert action == AuditAction.BOOKED
        assert occurred_at == now

    def test_reschedule_save_writes_rescheduled_audit(self):
        from tests.scheduling.fakes import InMemoryAppointmentRepository
        repo = InMemoryAppointmentRepository()
        appt = _make_appointment()
        repo.add(appt)
        now = _utc(9)
        appt.reschedule(_range(12, 14), now=now)
        repo.save(appt)
        assert any(a[1] == AuditAction.RESCHEDULED for a in repo.audits)

    def test_cancel_save_writes_cancelled_audit(self):
        from tests.scheduling.fakes import InMemoryAppointmentRepository
        repo = InMemoryAppointmentRepository()
        appt = _make_appointment()
        repo.add(appt)
        now = _utc(10)
        appt.cancel(now=now)
        repo.save(appt)
        assert any(a[1] == AuditAction.CANCELLED for a in repo.audits)

    def test_add_details_save_writes_details_added_audit(self):
        from tests.scheduling.fakes import InMemoryAppointmentRepository
        repo = InMemoryAppointmentRepository()
        appt = _make_appointment()
        repo.add(appt)
        now = _utc(11)
        appt.add_details("Notes", now=now)
        repo.save(appt)
        assert any(a[1] == AuditAction.DETAILS_ADDED for a in repo.audits)

    def test_get_then_no_mutation_writes_nothing(self):
        from tests.scheduling.fakes import InMemoryAppointmentRepository
        repo = InMemoryAppointmentRepository()
        appt = _make_appointment()
        repo.add(appt)
        # drain on add above; now get and do nothing
        initial_count = len(repo.audits)
        _ = repo.get(appt.id)
        assert len(repo.audits) == initial_count

    def test_assign_external_event_writes_nothing(self):
        from tests.scheduling.fakes import InMemoryAppointmentRepository
        repo = InMemoryAppointmentRepository()
        appt = _make_appointment()
        repo.add(appt)
        appt.assign_external_event("evt-99")
        repo.save(appt)
        # Only the initial add-drain (empty, no record_booked called here).
        assert not any(True for _ in repo.audits)

    def test_multiple_operations_accumulate_in_order(self):
        from tests.scheduling.fakes import InMemoryAppointmentRepository
        repo = InMemoryAppointmentRepository()
        appt = _make_appointment()
        t1 = _utc(8)
        t2 = _utc(9)
        t3 = _utc(10)
        appt.record_booked(t1)
        repo.add(appt)
        appt.reschedule(_range(12, 14), now=t2)
        repo.save(appt)
        appt.cancel(now=t3)
        repo.save(appt)
        actions = [a[1] for a in repo.audits]
        assert actions == [AuditAction.BOOKED, AuditAction.RESCHEDULED, AuditAction.CANCELLED]


# ---------------------------------------------------------------------------
# Integration test: real Postgres via testcontainers
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def pg_engine_audit():
    """Start a Postgres 16 container, run all migrations, yield an engine."""
    from alembic import command as alembic_command
    from alembic.config import Config as AlembicConfig
    from sqlalchemy import create_engine
    from testcontainers.postgres import PostgresContainer
    import pathlib

    with PostgresContainer("postgres:16", driver="psycopg") as pg:
        url = pg.get_connection_url()
        os.environ["DATABASE_URL"] = url

        cfg = AlembicConfig()
        cfg.set_main_option(
            "script_location",
            str(pathlib.Path(__file__).parents[2] / "alembic"),
        )
        cfg.set_main_option("sqlalchemy.url", url)
        alembic_command.upgrade(cfg, "head")

        engine = create_engine(url)
        yield engine
        engine.dispose()
        del os.environ["DATABASE_URL"]


@pytest.fixture
def pg_session_audit(pg_engine_audit):
    """Yield a session inside a savepoint; roll back after each test."""
    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=pg_engine_audit, expire_on_commit=False)
    with Session() as sess:
        with sess.begin():
            sess.begin_nested()
            yield sess
            sess.rollback()


class TestSqlAlchemyAuditIntegration:
    """book → reschedule → cancel writes exactly three audit rows in the correct order."""

    def test_book_reschedule_cancel_audit_rows(self, pg_session_audit):
        from sqlalchemy import text
        from fsm.scheduling.adapters.repositories import SqlAlchemyAppointmentRepository

        repo = SqlAlchemyAppointmentRepository(pg_session_audit)
        appt = _make_appointment()
        t1 = _utc(8)
        t2 = _utc(9)
        t3 = _utc(10)

        # Book
        appt.record_booked(t1)
        repo.add(appt)

        # Reschedule
        appt.reschedule(_range(12, 14), now=t2)
        repo.save(appt)

        # Cancel
        appt.cancel(now=t3)
        repo.save(appt)

        rows = pg_session_audit.execute(
            text(
                "SELECT action, occurred_at FROM appointment_audit "
                "WHERE appointment_id = :aid ORDER BY occurred_at"
            ),
            {"aid": appt.id},
        ).fetchall()

        assert len(rows) == 3
        assert rows[0].action == AuditAction.BOOKED.value
        assert rows[1].action == AuditAction.RESCHEDULED.value
        assert rows[2].action == AuditAction.CANCELLED.value

    def test_audit_rows_carry_correct_appointment_id(self, pg_session_audit):
        from sqlalchemy import text
        from fsm.scheduling.adapters.repositories import SqlAlchemyAppointmentRepository

        repo = SqlAlchemyAppointmentRepository(pg_session_audit)
        appt = _make_appointment()
        now = _utc(8)
        appt.record_booked(now)
        repo.add(appt)

        rows = pg_session_audit.execute(
            text("SELECT appointment_id FROM appointment_audit WHERE appointment_id = :aid"),
            {"aid": appt.id},
        ).fetchall()
        assert len(rows) == 1
        assert rows[0].appointment_id == appt.id
