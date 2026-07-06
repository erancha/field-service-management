"""Integration test for the one-time attendee backfill against real Postgres.

Mirrors the pg_engine/session fixtures in tests/scheduling/adapters/test_persistence.py: a
Postgres 16 testcontainer migrated once per module, with each test running inside a rolled-back
savepoint for isolation.
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

from fsm.platform.backfill_customer_attendees import enqueue_attendee_backfill
from fsm.scheduling.adapters.orm import AppointmentRow
from fsm.scheduling.adapters.outbox_repository import SqlAlchemyOutboxRepository


@pytest.fixture(scope="module")
def pg_engine():
    """Start a Postgres 16 container, run migrations, yield an engine."""
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
    """Yield a session inside a savepoint; roll back after each test."""
    Session = sessionmaker(bind=pg_engine, expire_on_commit=False)
    with Session() as sess:
        with sess.begin():
            sess.begin_nested()
            yield sess
            sess.rollback()


@pytest.fixture
def seed_appointment(session):
    """Insert an AppointmentRow with the given status/start/external_event_id and return it."""

    def _seed(*, status: str, start: datetime, external_event_id: str | None) -> AppointmentRow:
        row = AppointmentRow(
            id=uuid.uuid4(),
            service_call_id=uuid.uuid4(),
            technician_id=uuid.uuid4(),
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


def test_backfills_only_active_future_projected(session, seed_appointment):
    now = datetime(2026, 7, 6, tzinfo=timezone.utc)
    a = seed_appointment(status="BOOKED", start=now + timedelta(days=1), external_event_id="e1")
    seed_appointment(status="CANCELLED", start=now + timedelta(days=1), external_event_id="e2")
    seed_appointment(status="BOOKED", start=now - timedelta(days=1), external_event_id="e3")
    seed_appointment(status="BOOKED", start=now + timedelta(days=1), external_event_id=None)

    count = enqueue_attendee_backfill(session, now=now)
    assert count == 1

    entry = SqlAlchemyOutboxRepository(session).claim_next()
    assert entry.appointment_id == a.id
    assert entry.operation.value == "UPDATE"
