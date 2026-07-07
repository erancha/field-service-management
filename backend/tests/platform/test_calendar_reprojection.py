"""Integration test for re-projecting a technician's appointments onto a fresh calendar.

Mirrors the pg_engine/session fixtures used across the platform integration tests: a Postgres 16
testcontainer migrated once per module, with each test running inside a rolled-back savepoint.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from fsm.platform.calendar_reprojection import reproject_active_appointments
from fsm.scheduling.adapters.orm import AppointmentRow
from fsm.scheduling.adapters.outbox_repository import SqlAlchemyOutboxRepository


@pytest.fixture(scope="module")
def pg_engine():
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16", driver="psycopg") as pg:
        url = pg.get_connection_url()
        os.environ["DATABASE_URL"] = url

        cfg = AlembicConfig()
        cfg.set_main_option(
            "script_location",
            str(__import__("pathlib").Path(__file__).parents[2] / "alembic"),
        )
        cfg.set_main_option("sqlalchemy.url", url)
        alembic_command.upgrade(cfg, "head")

        engine = create_engine(url)
        yield engine
        engine.dispose()

        del os.environ["DATABASE_URL"]


@pytest.fixture
def session(pg_engine):
    Session = sessionmaker(bind=pg_engine, expire_on_commit=False)
    with Session() as sess:
        with sess.begin():
            sess.begin_nested()
            yield sess
            sess.rollback()


@pytest.fixture
def seed_appointment(session):
    def _seed(
        *,
        technician_id: uuid.UUID,
        status: str,
        start: datetime,
        external_event_id: str | None,
    ) -> AppointmentRow:
        row = AppointmentRow(
            id=uuid.uuid4(),
            service_call_id=uuid.uuid4(),
            technician_id=technician_id,
            customer_id=uuid.uuid4(),
            start_at=start,
            end_at=start + timedelta(hours=1),
            status=status,
            details=None,
            external_event_id=external_event_id,
            created_at=start,
            updated_at=start,
        )
        session.add(row)
        session.flush()
        return row

    return _seed


def test_reprojects_only_this_technicians_active_future_appointments(session, seed_appointment):
    now = datetime(2026, 7, 6, tzinfo=timezone.utc)
    tech = uuid.uuid4()
    other_tech = uuid.uuid4()

    projected = seed_appointment(
        technician_id=tech, status="SCHEDULED", start=now + timedelta(days=1), external_event_id="stale-1"
    )
    never_projected = seed_appointment(
        technician_id=tech, status="SCHEDULED", start=now + timedelta(days=2), external_event_id=None
    )
    # Excluded: cancelled, past, and another technician's appointment.
    seed_appointment(
        technician_id=tech, status="CANCELLED", start=now + timedelta(days=1), external_event_id="c1"
    )
    seed_appointment(
        technician_id=tech, status="SCHEDULED", start=now - timedelta(days=1), external_event_id="p1"
    )
    seed_appointment(
        technician_id=other_tech, status="SCHEDULED", start=now + timedelta(days=1), external_event_id="o1"
    )

    count = reproject_active_appointments(session, tech, now=now)

    assert count == 2
    entries = SqlAlchemyOutboxRepository(session).list_pending(10)
    assert {e.appointment_id for e in entries} == {projected.id, never_projected.id}
    assert all(e.operation.value == "CREATE" for e in entries)
