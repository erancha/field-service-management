"""Tests for build_dispatcher and run_forever in dispatcher_runner.

Uses real Postgres (testcontainers) with unconfigured Google settings so the
NullCalendarPort is used. This exercises the full DB-to-dispatcher pipeline
without touching external services.
"""
from __future__ import annotations

import os
import pathlib
import threading
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from fsm.platform.config import Settings
from fsm.platform.db import create_engine_from_settings, session_factory
from fsm.platform.dispatcher_runner import build_dispatcher, make_auth_disconnect_handler, run_forever
from fsm.calendar.adapters.orm import CalendarConnectionRow
from fsm.scheduling.adapters.orm import AppointmentRow, OutboxRow


# ---------------------------------------------------------------------------
# Module-scoped Postgres container
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def pg_engine():
    from alembic import command as alembic_command
    from alembic.config import Config as AlembicConfig
    from sqlalchemy import create_engine
    from testcontainers.postgres import PostgresContainer

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


@pytest.fixture(scope="module")
def pg_settings(pg_engine):
    url = str(pg_engine.url)
    return Settings(
        database_url=url,
        app_env="test",
        # Intentionally unconfigured so NullCalendarPort is used.
        google_client_id=None,
        google_client_secret=None,
        fsm_token_key=None,
        fsm_dispatch_enabled=False,
        fsm_dispatch_interval_seconds=0.01,
    )


@pytest.fixture
def pg_session_factory(pg_engine):
    return sessionmaker(bind=pg_engine, expire_on_commit=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TZ = timezone.utc
_NOW = datetime(2024, 6, 10, 8, 0, tzinfo=_TZ)


def _seed_appointment_and_outbox(session, *, tech_id=None) -> tuple[uuid.UUID, uuid.UUID]:
    """Insert a minimal AppointmentRow and a PENDING CREATE outbox entry; return (appt_id, outbox_id)."""
    appt_id = uuid.uuid4()
    outbox_id = uuid.uuid4()
    if tech_id is None:
        tech_id = uuid.uuid4()

    session.add(AppointmentRow(
        id=appt_id,
        service_call_id=uuid.uuid4(),
        technician_id=tech_id,
        customer_id=uuid.uuid4(),
        start_at=datetime(2024, 6, 10, 9, 0, tzinfo=_TZ),
        end_at=datetime(2024, 6, 10, 11, 0, tzinfo=_TZ),
        status="SCHEDULED",
        details=None,
        external_event_id=None,
        created_at=_NOW,
        updated_at=_NOW,
    ))
    session.add(OutboxRow(
        id=outbox_id,
        operation="CREATE",
        appointment_id=appt_id,
        external_event_id=None,
        status="PENDING",
        attempts=0,
    ))
    session.flush()
    return appt_id, outbox_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBuildDispatcher:
    def test_run_once_processes_create_entry_and_sets_external_event_id(
        self,
        pg_session_factory,
        pg_settings,
    ):
        appt_id = None
        outbox_id = None

        # Seed data in its own committed transaction so the dispatcher can see it.
        with pg_session_factory() as seed_session:
            with seed_session.begin():
                appt_id, outbox_id = _seed_appointment_and_outbox(seed_session)

        dispatcher = build_dispatcher(pg_session_factory, pg_settings)
        count = dispatcher.run_once()

        assert count == 1

        # Read back with a fresh session to verify the committed state.
        with pg_session_factory() as read_session:
            outbox_row = read_session.get(OutboxRow, outbox_id)
            assert outbox_row.status == "PROCESSED"

            appt_row = read_session.get(AppointmentRow, appt_id)
            # NullCalendarPort generates a synthetic null-evt-<uuid> id.
            assert appt_row.external_event_id is not None
            assert appt_row.external_event_id.startswith("null-evt-")


class TestRunForever:
    def test_stop_event_exits_the_loop(self, pg_session_factory, pg_settings):
        stop = threading.Event()
        results = []

        def _target():
            results.append("started")
            run_forever(pg_session_factory, pg_settings, stop)
            results.append("stopped")

        thread = threading.Thread(target=_target, daemon=True)
        thread.start()
        stop.set()
        thread.join(timeout=5.0)
        assert not thread.is_alive(), "run_forever did not exit within 5 seconds"
        assert results == ["started", "stopped"]


class TestAuthDisconnectOnDispatchError:
    """Verify that a calendar auth error during dispatch marks the connection DISCONNECTED."""

    def test_auth_error_disconnects_connection(self, pg_session_factory, pg_settings):
        from cryptography.fernet import Fernet
        from fsm.calendar.adapters.token_cipher import FernetTokenCipher
        from fsm.platform.calendar_resolver import build_calendar_resolver
        from fsm.scheduling.adapters.unit_of_work import SqlAlchemyUnitOfWork
        from fsm.scheduling.application.calendar_projection_dispatcher import (
            CalendarProjectionDispatcher,
        )

        tech_id = uuid.uuid4()
        fernet_key = Fernet.generate_key().decode()
        encrypted_token = FernetTokenCipher(fernet_key).encrypt("fake-refresh-token")

        settings_with_creds = Settings(
            database_url=pg_settings.database_url.get_secret_value(),
            app_env="test",
            google_client_id="fake-client-id",
            google_client_secret="fake-secret",
            fsm_token_key=fernet_key,
            fsm_dispatch_enabled=False,
            fsm_dispatch_interval_seconds=0.01,
        )

        # Seed a CONNECTED calendar connection and appointment with CREATE outbox entry.
        with pg_session_factory() as seed_session:
            with seed_session.begin():
                seed_session.add(CalendarConnectionRow(
                    technician_id=tech_id,
                    fsm_calendar_id=f"cal-{tech_id}",
                    encrypted_refresh_token=encrypted_token,
                    status="CONNECTED",
                    sync_token=None,
                ))
                appt_id, outbox_id = _seed_appointment_and_outbox(seed_session, tech_id=tech_id)

        # A client factory that raises a RefreshError-like auth error.
        class RefreshError(Exception):
            pass

        def auth_failing_client_factory(**kwargs):
            class _Client:
                def import_event(self, calendar_id, body):
                    raise RefreshError("invalid_grant: Token has been revoked.")

                def insert_event(self, *a, **kw):
                    raise RefreshError("invalid_grant: Token has been revoked.")

                def update_event(self, *a, **kw):
                    pass

                def delete_event(self, *a, **kw):
                    pass

                def query_busy(self, *a, **kw):
                    return []

            return _Client()

        error_handler = make_auth_disconnect_handler(pg_session_factory, settings_with_creds)
        calendar_resolver = build_calendar_resolver(
            pg_session_factory,
            settings_with_creds,
            client_factory=auth_failing_client_factory,
        )
        dispatcher = CalendarProjectionDispatcher(
            uow_factory=lambda: SqlAlchemyUnitOfWork(pg_session_factory),
            calendar_resolver=calendar_resolver,
            on_calendar_error=error_handler,
        )

        dispatcher.run_once()

        # The connection must now be DISCONNECTED.
        with pg_session_factory() as read_session:
            conn_row = read_session.get(CalendarConnectionRow, tech_id)
            assert conn_row is not None
            assert conn_row.status == "DISCONNECTED", (
                f"Expected DISCONNECTED, got {conn_row.status!r}"
            )
