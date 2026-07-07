"""Integration test for poll_once in sync_runner against real Postgres.

Seeds a CONNECTED calendar connection and an appointment, injects a fake
client_factory that returns one reschedule event, calls poll_once, and verifies
the appointment is rescheduled in the DB and the sync token is persisted.
"""
from __future__ import annotations

import os
import pathlib
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from fsm.platform.config import Settings
from fsm.platform.sync_runner import poll_once
from fsm.scheduling.adapters.orm import AppointmentRow
from fsm.google_calendar.adapters.orm import CalendarConnectionRow


_TZ = timezone.utc
# The reconciler validates inbound moves against the default Sun–Thu 09:00–17:00 schedule in the
# service-region zone Asia/Jerusalem. 2024-06-10 is a Monday in IDT (UTC+3), so 09:00–17:00 local is
# 06:00–14:00 UTC; the move below (13:00–15:00 local) lands inside that window and is accepted.
_APPT_START = datetime(2024, 6, 10, 9, 0, tzinfo=_TZ)
_APPT_END = datetime(2024, 6, 10, 11, 0, tzinfo=_TZ)
_NEW_START = datetime(2024, 6, 10, 10, 0, tzinfo=_TZ)
_NEW_END = datetime(2024, 6, 10, 12, 0, tzinfo=_TZ)
_APPT_UPDATED_AT = datetime(2024, 6, 10, 8, 0, tzinfo=_TZ)
# The inbound change must be strictly newer than _APPT_UPDATED_AT
_EVENT_UPDATED_AT = datetime(2024, 6, 10, 8, 30, tzinfo=_TZ)
_NEXT_SYNC_TOKEN = "sync-token-after-poll"


@pytest.fixture(scope="module")
def pg_engine():
    from alembic import command as alembic_command
    from alembic.config import Config as AlembicConfig
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
    from cryptography.fernet import Fernet

    fernet_key = Fernet.generate_key().decode()
    url = str(pg_engine.url)
    return Settings(
        database_url=url,
        app_env="test",
        google_client_id="fake-client-id",
        google_client_secret="fake-client-secret",
        fsm_token_key=fernet_key,
        fsm_dispatch_enabled=False,
        fsm_dispatch_interval_seconds=0.01,
        fsm_sync_enabled=False,
        fsm_sync_interval_seconds=0.01,
    )


@pytest.fixture
def pg_session_factory(pg_engine):
    return sessionmaker(bind=pg_engine, expire_on_commit=False)


class TestPollOnce:
    def test_reschedule_applied_and_sync_token_persisted(
        self, pg_session_factory, pg_settings
    ):

        appt_id = uuid.uuid4()
        tech_id = uuid.uuid4()
        cal_id = f"cal-test-{uuid.uuid4()}"
        fake_refresh_token = "fake-refresh-token"

        fernet_key = pg_settings.fsm_token_key.get_secret_value()
        from fsm.google_calendar.adapters.token_cipher import FernetTokenCipher
        encrypted_token = FernetTokenCipher(fernet_key).encrypt(fake_refresh_token)

        # Seed a CONNECTED calendar connection and an appointment in committed transactions.
        with pg_session_factory() as seed_session:
            with seed_session.begin():
                seed_session.add(CalendarConnectionRow(
                    technician_id=tech_id,
                    fsm_calendar_id=cal_id,
                    encrypted_refresh_token=encrypted_token,
                    status="CONNECTED",
                    sync_token=None,
                ))
                seed_session.add(AppointmentRow(
                    id=appt_id,
                    service_call_id=uuid.uuid4(),
                    technician_id=tech_id,
                    customer_id=uuid.uuid4(),
                    start_at=_APPT_START,
                    end_at=_APPT_END,
                    status="SCHEDULED",
                    details=None,
                    external_event_id=None,
                    created_at=_APPT_UPDATED_AT,
                    updated_at=_APPT_UPDATED_AT,
                ))

        raw_events = [
            {
                "iCalUID": f"fsm-{appt_id}@fsm.local",
                "status": "confirmed",
                "start": {"dateTime": _NEW_START.isoformat()},
                "end": {"dateTime": _NEW_END.isoformat()},
                "description": None,
                "updated": _EVENT_UPDATED_AT.isoformat(),
            }
        ]

        class FakeClient:
            def list_changes(self, calendar_id, sync_token):
                return raw_events, _NEXT_SYNC_TOKEN

        def fake_client_factory(**kwargs):
            return FakeClient()

        count = poll_once(pg_session_factory, pg_settings, client_factory=fake_client_factory)
        assert count == 1

        # Verify the appointment was rescheduled.
        with pg_session_factory() as read_session:
            appt_row = read_session.get(AppointmentRow, appt_id)
            assert appt_row.start_at.replace(tzinfo=_TZ) == _NEW_START
            assert appt_row.end_at.replace(tzinfo=_TZ) == _NEW_END
            assert appt_row.status == "RESCHEDULED"

        # Verify the sync token was stored.
        with pg_session_factory() as read_session:
            conn_row = read_session.get(CalendarConnectionRow, tech_id)
            assert conn_row.sync_token == _NEXT_SYNC_TOKEN

    def test_auth_error_disconnects_and_poll_does_not_raise(
        self, pg_session_factory, pg_settings
    ):
        """A connected technician whose list_changes raises an auth error results in
        the connection being marked DISCONNECTED, and poll_once does not raise."""
        from fsm.google_calendar.adapters.token_cipher import FernetTokenCipher

        tech_id = uuid.uuid4()
        cal_id = f"cal-auth-err-{uuid.uuid4()}"

        fernet_key = pg_settings.fsm_token_key.get_secret_value()
        encrypted_token = FernetTokenCipher(fernet_key).encrypt("fake-refresh-token")

        with pg_session_factory() as seed_session:
            with seed_session.begin():
                seed_session.add(CalendarConnectionRow(
                    technician_id=tech_id,
                    fsm_calendar_id=cal_id,
                    encrypted_refresh_token=encrypted_token,
                    status="CONNECTED",
                    sync_token=None,
                ))

        class RefreshError(Exception):
            pass

        class AuthFailingClient:
            def list_changes(self, calendar_id, sync_token):
                raise RefreshError("invalid_grant: Token has been revoked.")

        def auth_failing_factory(**kwargs):
            return AuthFailingClient()

        count = poll_once(pg_session_factory, pg_settings, client_factory=auth_failing_factory)
        assert count == 0

        with pg_session_factory() as read_session:
            conn_row = read_session.get(CalendarConnectionRow, tech_id)
            assert conn_row is not None
            assert conn_row.status == "DISCONNECTED", (
                f"Expected DISCONNECTED, got {conn_row.status!r}"
            )

    def test_customer_decline_cancels_appointment(self, pg_session_factory, pg_settings):
        appt_id = uuid.uuid4()
        tech_id = uuid.uuid4()
        cal_id = f"cal-test-{uuid.uuid4()}"

        fernet_key = pg_settings.fsm_token_key.get_secret_value()
        from fsm.google_calendar.adapters.token_cipher import FernetTokenCipher
        encrypted_token = FernetTokenCipher(fernet_key).encrypt("fake-refresh-token")

        with pg_session_factory() as seed_session:
            with seed_session.begin():
                seed_session.add(CalendarConnectionRow(
                    technician_id=tech_id,
                    fsm_calendar_id=cal_id,
                    encrypted_refresh_token=encrypted_token,
                    status="CONNECTED",
                    sync_token=None,
                ))
                seed_session.add(AppointmentRow(
                    id=appt_id,
                    service_call_id=uuid.uuid4(),
                    technician_id=tech_id,
                    customer_id=uuid.uuid4(),
                    start_at=_APPT_START,
                    end_at=_APPT_END,
                    status="SCHEDULED",
                    details=None,
                    external_event_id="evt-decline-test",
                    created_at=_APPT_UPDATED_AT,
                    updated_at=_APPT_UPDATED_AT,
                ))

        raw_events = [
            {
                "iCalUID": f"fsm-{appt_id}@fsm.local",
                "status": "confirmed",
                "start": {"dateTime": _APPT_START.isoformat()},
                "end": {"dateTime": _APPT_END.isoformat()},
                "updated": _EVENT_UPDATED_AT.isoformat(),
                "attendees": [
                    {"email": "customer@example.com", "responseStatus": "declined"}
                ],
            }
        ]

        class FakeClient:
            def list_changes(self, calendar_id, sync_token):
                return raw_events, _NEXT_SYNC_TOKEN

        count = poll_once(
            pg_session_factory, pg_settings, client_factory=lambda **kwargs: FakeClient()
        )
        assert count == 1

        with pg_session_factory() as read_session:
            appt_row = read_session.get(AppointmentRow, appt_id)
            assert appt_row.status == "CANCELLED"
