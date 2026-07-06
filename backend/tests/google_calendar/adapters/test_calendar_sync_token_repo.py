"""Integration tests for sync token repository methods against real Postgres.

A Postgres 16 container is started once per module via testcontainers, with all
Alembic migrations applied. Each test runs inside its own savepoint rolled back
after the test.
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
from fsm.google_calendar.domain.errors import NotFoundError


def _make_connection(
    *,
    technician_id: uuid.UUID | None = None,
    status: CalendarConnectionStatus = CalendarConnectionStatus.CONNECTED,
) -> CalendarConnection:
    return CalendarConnection(
        technician_id=technician_id or uuid.uuid4(),
        fsm_calendar_id="cal-test-123",
        status=status,
    )


@pytest.fixture(scope="module")
def pg_engine():
    """Start a Postgres 16 container, run all migrations, yield an engine."""
    with PostgresContainer("postgres:16", driver="psycopg") as pg:
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


class TestSyncTokenMethods:
    def test_set_then_get_round_trips(self, session):
        repo = SqlAlchemyCalendarConnectionRepository(session)
        conn = _make_connection()
        repo.add(conn, "encrypted-token")
        repo.set_sync_token(conn.technician_id, "sync-token-v1")
        assert repo.get_sync_token(conn.technician_id) == "sync-token-v1"

    def test_get_sync_token_returns_none_when_not_set(self, session):
        repo = SqlAlchemyCalendarConnectionRepository(session)
        conn = _make_connection()
        repo.add(conn, "encrypted-token")
        assert repo.get_sync_token(conn.technician_id) is None

    def test_set_sync_token_unknown_raises_not_found(self, session):
        repo = SqlAlchemyCalendarConnectionRepository(session)
        with pytest.raises(NotFoundError):
            repo.set_sync_token(uuid.uuid4(), "token")

    def test_get_sync_token_unknown_raises_not_found(self, session):
        repo = SqlAlchemyCalendarConnectionRepository(session)
        with pytest.raises(NotFoundError):
            repo.get_sync_token(uuid.uuid4())

    def test_set_sync_token_overwrites_existing(self, session):
        repo = SqlAlchemyCalendarConnectionRepository(session)
        conn = _make_connection()
        repo.add(conn, "encrypted-token")
        repo.set_sync_token(conn.technician_id, "first-token")
        repo.set_sync_token(conn.technician_id, "second-token")
        assert repo.get_sync_token(conn.technician_id) == "second-token"

    def test_set_sync_token_to_none_clears_it(self, session):
        repo = SqlAlchemyCalendarConnectionRepository(session)
        conn = _make_connection()
        repo.add(conn, "encrypted-token")
        repo.set_sync_token(conn.technician_id, "some-token")
        repo.set_sync_token(conn.technician_id, None)
        assert repo.get_sync_token(conn.technician_id) is None


class TestListConnected:
    def test_returns_connected_rows_only(self, session):
        repo = SqlAlchemyCalendarConnectionRepository(session)
        connected = _make_connection(status=CalendarConnectionStatus.CONNECTED)
        disconnected = _make_connection(status=CalendarConnectionStatus.DISCONNECTED)
        repo.add(connected, "enc-token-1")
        repo.add(disconnected, "enc-token-2")

        results = repo.list_connected()
        ids = {c.technician_id for c in results}
        assert connected.technician_id in ids
        assert disconnected.technician_id not in ids

    def test_excludes_disconnected_after_disconnect_and_save(self, session):
        repo = SqlAlchemyCalendarConnectionRepository(session)
        conn = _make_connection(status=CalendarConnectionStatus.CONNECTED)
        repo.add(conn, "enc-token")

        conn.disconnect()
        repo.save(conn)

        results = repo.list_connected()
        ids = {c.technician_id for c in results}
        assert conn.technician_id not in ids

    def test_returns_empty_when_no_connections(self, session):
        repo = SqlAlchemyCalendarConnectionRepository(session)
        results = repo.list_connected()
        assert results == []
