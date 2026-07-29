"""Integration tests for calendar connection repository against real Postgres.

A Postgres 16 container is started once per module via testcontainers. All
Alembic migrations (0001+0002+0003) are applied, then each test runs inside its
own savepoint that is rolled back after the test.
"""
from __future__ import annotations

import os
import pathlib
import uuid

import pytest
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from testcontainers.postgres import PostgresContainer

from fsm.google_calendar.adapters.repositories import SqlAlchemyCalendarConnectionRepository
from fsm.google_calendar.domain.connection import CalendarConnection, CalendarConnectionStatus
from fsm.google_calendar.domain.errors import DuplicateTechnicianError, NotFoundError


def _make_connection(*, technician_id: uuid.UUID | None = None) -> CalendarConnection:
    return CalendarConnection(
        technician_id=technician_id or uuid.uuid4(),
        fsm_calendar_id="cal-abc-123",
        status=CalendarConnectionStatus.CONNECTED,
    )


@pytest.fixture(scope="module")
def pg_engine():
    """Start a Postgres 16 container, run all migrations, yield an engine."""
    with PostgresContainer("pgvector/pgvector:pg16", driver="psycopg") as pg:
        url = pg.get_connection_url()
        os.environ["DATABASE_URL"] = url

        cfg = AlembicConfig()
        cfg.set_main_option(
            "script_location",
            str(pathlib.Path(__file__).parents[3] / "alembic"),
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


class TestSqlAlchemyCalendarConnectionRepository:
    def test_add_then_get_round_trips(self, session):
        repo = SqlAlchemyCalendarConnectionRepository(session)
        conn = _make_connection()
        repo.add(conn, "encrypted-token-blob")
        fetched = repo.get(conn.technician_id)
        assert fetched.technician_id == conn.technician_id
        assert fetched.fsm_calendar_id == conn.fsm_calendar_id
        assert fetched.status == CalendarConnectionStatus.CONNECTED

    def test_get_unknown_technician_raises_not_found(self, session):
        repo = SqlAlchemyCalendarConnectionRepository(session)
        with pytest.raises(NotFoundError):
            repo.get(uuid.uuid4())

    def test_get_encrypted_token_returns_stored_blob(self, session):
        repo = SqlAlchemyCalendarConnectionRepository(session)
        conn = _make_connection()
        blob = "some-encrypted-token-blob"
        repo.add(conn, blob)
        assert repo.get_encrypted_token(conn.technician_id) == blob

    def test_get_encrypted_token_unknown_raises_not_found(self, session):
        repo = SqlAlchemyCalendarConnectionRepository(session)
        with pytest.raises(NotFoundError):
            repo.get_encrypted_token(uuid.uuid4())

    def test_duplicate_technician_raises_domain_error(self, session):
        repo = SqlAlchemyCalendarConnectionRepository(session)
        tech_id = uuid.uuid4()
        conn1 = _make_connection(technician_id=tech_id)
        conn2 = _make_connection(technician_id=tech_id)
        repo.add(conn1, "token-1")
        with pytest.raises(DuplicateTechnicianError):
            repo.add(conn2, "token-2")

    def test_save_persists_status_mutation(self, session):
        repo = SqlAlchemyCalendarConnectionRepository(session)
        conn = _make_connection()
        repo.add(conn, "token")
        conn.disconnect()
        repo.save(conn)
        fetched = repo.get(conn.technician_id)
        assert fetched.status == CalendarConnectionStatus.DISCONNECTED

    def test_reconnect_replaces_token_and_reactivates_reusing_calendar(self, session):
        repo = SqlAlchemyCalendarConnectionRepository(session)
        conn = _make_connection()
        repo.add(conn, "stale-token")
        conn.disconnect()
        repo.save(conn)

        repo.reconnect(conn.technician_id, "fresh-token")

        fetched = repo.get(conn.technician_id)
        assert fetched.status == CalendarConnectionStatus.CONNECTED
        assert fetched.fsm_calendar_id == conn.fsm_calendar_id
        assert repo.get_encrypted_token(conn.technician_id) == "fresh-token"

    def test_reconnect_unknown_technician_raises_not_found(self, session):
        repo = SqlAlchemyCalendarConnectionRepository(session)
        with pytest.raises(NotFoundError):
            repo.reconnect(uuid.uuid4(), "token")

    def test_reprovision_repoints_calendar_token_and_clears_sync_token(self, session):
        repo = SqlAlchemyCalendarConnectionRepository(session)
        conn = _make_connection()
        repo.add(conn, "stale-token")
        repo.set_sync_token(conn.technician_id, "sync-token-from-old-calendar")

        repo.reprovision(conn.technician_id, "cal-replacement-999", "fresh-token")

        fetched = repo.get(conn.technician_id)
        assert fetched.status == CalendarConnectionStatus.CONNECTED
        assert fetched.fsm_calendar_id == "cal-replacement-999"
        assert repo.get_encrypted_token(conn.technician_id) == "fresh-token"
        # The stale sync token must not carry over: it belongs to the deleted calendar.
        assert repo.get_sync_token(conn.technician_id) is None

    def test_reprovision_unknown_technician_raises_not_found(self, session):
        repo = SqlAlchemyCalendarConnectionRepository(session)
        with pytest.raises(NotFoundError):
            repo.reprovision(uuid.uuid4(), "cal-x", "token")
