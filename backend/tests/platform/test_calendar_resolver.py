"""Tests for build_calendar_resolver — the per-technician CalendarPort resolver.

Uses an in-memory fake repository so the tests are fast and need no database.
A separate integration class exercises the real SqlAlchemy repo against Postgres.
"""
from __future__ import annotations

import os
import pathlib
import uuid
from datetime import datetime, timezone
from typing import Callable
from unittest.mock import MagicMock

import pytest
from pydantic import SecretStr

from fsm.platform.calendar_bridge.google_calendar import GoogleCalendarAdapter
from fsm.google_calendar.domain.connection import CalendarConnection, CalendarConnectionStatus
from fsm.google_calendar.domain.errors import NotFoundError
from fsm.google_calendar.adapters.token_cipher import FernetTokenCipher
from fsm.platform.calendar_resolver import build_calendar_resolver
from fsm.platform.config import Settings
from fsm.platform.dev_adapters import NullCalendarPort
from fsm.scheduling.domain.appointment import Appointment, AppointmentStatus
from fsm.scheduling.domain.appointment_context import AppointmentContext
from fsm.scheduling.domain.time_range import TimeRange


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_FERNET_KEY = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="


def _unconfigured_settings() -> Settings:
    return Settings(
        database_url="postgresql+psycopg://x:x@localhost/x",
        google_client_id=None,
        google_client_secret=None,
        fsm_token_key=None,
    )


def _configured_settings() -> Settings:
    return Settings(
        database_url="postgresql+psycopg://x:x@localhost/x",
        google_client_id="test-client-id",
        google_client_secret=SecretStr("test-client-secret"),
        fsm_token_key=SecretStr(_VALID_FERNET_KEY),
    )


class FakeCalendarConnectionRepository:
    """In-memory double for SqlAlchemyCalendarConnectionRepository."""

    def __init__(self) -> None:
        self._connections: dict[uuid.UUID, CalendarConnection] = {}
        self._tokens: dict[uuid.UUID, str] = {}

    def add(self, connection: CalendarConnection, encrypted_token: str) -> None:
        self._connections[connection.technician_id] = connection
        self._tokens[connection.technician_id] = encrypted_token

    def get(self, technician_id: uuid.UUID) -> CalendarConnection:
        if technician_id not in self._connections:
            raise NotFoundError(f"No connection for {technician_id}")
        return self._connections[technician_id]

    def get_encrypted_token(self, technician_id: uuid.UUID) -> str:
        if technician_id not in self._tokens:
            raise NotFoundError(f"No token for {technician_id}")
        return self._tokens[technician_id]


class FakeSessionContext:
    """Minimal session-factory double that yields a fake repo instead of a real session."""

    def __init__(self, repo: FakeCalendarConnectionRepository) -> None:
        self._repo = repo

    def __call__(self) -> "_FakeSession":
        return _FakeSession(self._repo)


class _FakeSession:
    def __init__(self, repo: FakeCalendarConnectionRepository) -> None:
        self._repo = repo

    def __enter__(self) -> "_FakeSession":
        return self

    def __exit__(self, *_: object) -> None:
        pass


# ---------------------------------------------------------------------------
# Unconfigured settings always yield NullCalendarPort
# ---------------------------------------------------------------------------

class TestUnconfiguredSettings:
    def test_any_technician_id_resolves_to_null_calendar(self):
        settings = _unconfigured_settings()
        resolver = build_calendar_resolver(
            session_factory=lambda: MagicMock(),
            settings=settings,
        )
        result = resolver(uuid.uuid4())
        assert isinstance(result, NullCalendarPort)

    def test_returns_null_when_only_client_id_missing(self):
        settings = Settings(
            database_url="postgresql+psycopg://x:x@localhost/x",
            google_client_id=None,
            google_client_secret=SecretStr("secret"),
            fsm_token_key=SecretStr(_VALID_FERNET_KEY),
        )
        resolver = build_calendar_resolver(session_factory=lambda: MagicMock(), settings=settings)
        assert isinstance(resolver(uuid.uuid4()), NullCalendarPort)

    def test_returns_null_when_only_client_secret_missing(self):
        settings = Settings(
            database_url="postgresql+psycopg://x:x@localhost/x",
            google_client_id="id",
            google_client_secret=None,
            fsm_token_key=SecretStr(_VALID_FERNET_KEY),
        )
        resolver = build_calendar_resolver(session_factory=lambda: MagicMock(), settings=settings)
        assert isinstance(resolver(uuid.uuid4()), NullCalendarPort)

    def test_returns_null_when_only_token_key_missing(self):
        settings = Settings(
            database_url="postgresql+psycopg://x:x@localhost/x",
            google_client_id="id",
            google_client_secret=SecretStr("secret"),
            fsm_token_key=None,
        )
        resolver = build_calendar_resolver(session_factory=lambda: MagicMock(), settings=settings)
        assert isinstance(resolver(uuid.uuid4()), NullCalendarPort)


# ---------------------------------------------------------------------------
# Configured settings with fake repo
# ---------------------------------------------------------------------------

class TestConfiguredSettings:
    def _make_repo_and_factory(self) -> tuple[FakeCalendarConnectionRepository, Callable]:
        from cryptography.fernet import Fernet

        repo = FakeCalendarConnectionRepository()
        # Fernet requires a proper key; use a real one to make encryption work.
        real_key = Fernet.generate_key().decode()

        def session_factory():
            class _Sess:
                def __enter__(self_):
                    return self_

                def __exit__(self_, *_: object) -> None:
                    pass

                def get(self_, model_cls, technician_id):
                    from fsm.google_calendar.adapters.orm import CalendarConnectionRow
                    if technician_id in repo._connections:
                        conn = repo._connections[technician_id]
                        row = CalendarConnectionRow(
                            technician_id=conn.technician_id,
                            fsm_calendar_id=conn.fsm_calendar_id,
                            encrypted_refresh_token=repo._tokens[technician_id],
                            status=conn.status.value,
                        )
                        return row
                    return None

            return _Sess()

        return repo, session_factory, real_key

    def test_unconnected_technician_resolves_to_null_calendar(self):
        from cryptography.fernet import Fernet

        real_key = Fernet.generate_key().decode()
        settings = Settings(
            database_url="postgresql+psycopg://x:x@localhost/x",
            google_client_id="test-id",
            google_client_secret=SecretStr("test-secret"),
            fsm_token_key=SecretStr(real_key),
        )

        def session_factory():
            class _Sess:
                def __enter__(self_):
                    return self_

                def __exit__(self_, *_: object) -> None:
                    pass

                def get(self_, model_cls, technician_id):
                    return None  # No row — technician not connected

            return _Sess()

        resolver = build_calendar_resolver(
            session_factory=session_factory,
            settings=settings,
        )
        result = resolver(uuid.uuid4())
        assert isinstance(result, NullCalendarPort)

    def test_connected_technician_resolves_to_google_adapter_with_correct_calendar_id(self):
        from cryptography.fernet import Fernet

        real_key = Fernet.generate_key().decode()
        settings = Settings(
            database_url="postgresql+psycopg://x:x@localhost/x",
            google_client_id="test-id",
            google_client_secret=SecretStr("test-secret"),
            fsm_token_key=SecretStr(real_key),
        )

        tech_id = uuid.uuid4()
        fsm_cal_id = "cal-abc-999"
        encrypted_token = FernetTokenCipher(real_key).encrypt("refresh-token-value")

        from fsm.google_calendar.adapters.orm import CalendarConnectionRow

        def session_factory():
            class _Sess:
                def __enter__(self_):
                    return self_

                def __exit__(self_, *_: object) -> None:
                    pass

                def get(self_, model_cls, tid):
                    if tid == tech_id:
                        return CalendarConnectionRow(
                            technician_id=tech_id,
                            fsm_calendar_id=fsm_cal_id,
                            encrypted_refresh_token=encrypted_token,
                            status="CONNECTED",
                        )
                    return None

            return _Sess()

        fake_client = MagicMock()
        fake_factory_calls = []

        def fake_client_factory(**kwargs):
            fake_factory_calls.append(kwargs)
            return fake_client

        resolver = build_calendar_resolver(
            session_factory=session_factory,
            settings=settings,
            client_factory=fake_client_factory,
        )
        result = resolver(tech_id)

        assert isinstance(result, GoogleCalendarAdapter)
        assert result._calendar_id == fsm_cal_id
        assert len(fake_factory_calls) == 1
        assert fake_factory_calls[0]["refresh_token"] == "refresh-token-value"
        assert fake_factory_calls[0]["client_id"] == "test-id"
        assert fake_factory_calls[0]["client_secret"] == "test-secret"


# ---------------------------------------------------------------------------
# Customer attendee wiring (build_email_resolver_via_factory as a real resolver caller)
# ---------------------------------------------------------------------------

class TestAttendeeEmailWiring:
    """Confirms build_email_resolver_via_factory's session_factory() call actually resolves
    an email end-to-end through the adapter the resolver returns, since Task 1 added the
    factory-based resolver without a caller exercising it against a session_factory."""

    def test_created_event_carries_resolved_customer_email_as_attendee(self) -> None:
        from cryptography.fernet import Fernet

        from fsm.google_calendar.adapters.orm import CalendarConnectionRow
        from fsm.identity.adapters.orm import UserRow

        real_key = Fernet.generate_key().decode()
        settings = Settings(
            database_url="postgresql+psycopg://x:x@localhost/x",
            google_client_id="test-id",
            google_client_secret=SecretStr("test-secret"),
            fsm_token_key=SecretStr(real_key),
        )

        tech_id = uuid.uuid4()
        customer_id = uuid.uuid4()
        fsm_cal_id = "cal-attendee-1"
        encrypted_token = FernetTokenCipher(real_key).encrypt("refresh-token-value")

        session_factory_calls = []

        def session_factory():
            session_factory_calls.append(1)

            class _Sess:
                def __enter__(self_):
                    return self_

                def __exit__(self_, *_: object) -> None:
                    pass

                def get(self_, model_cls, row_id):
                    if model_cls is CalendarConnectionRow and row_id == tech_id:
                        return CalendarConnectionRow(
                            technician_id=tech_id,
                            fsm_calendar_id=fsm_cal_id,
                            encrypted_refresh_token=encrypted_token,
                            status="CONNECTED",
                        )
                    if model_cls is UserRow and row_id == customer_id:
                        return UserRow(
                            id=customer_id,
                            google_sub="sub-1",
                            email="customer@example.com",
                            name="Ada Lovelace",
                            role="CUSTOMER",
                            role_status="APPROVED",
                        )
                    return None

            return _Sess()

        fake_client = MagicMock()
        fake_client.insert_event.return_value = {"id": "evt-attendee"}

        resolver = build_calendar_resolver(
            session_factory=session_factory,
            settings=settings,
            client_factory=lambda **_kwargs: fake_client,
        )
        adapter = resolver(tech_id)
        assert isinstance(adapter, GoogleCalendarAdapter)

        # The resolver's session_factory() is called once, eagerly, to load the calendar
        # connection; the attendee_email resolver only opens its own session lazily when
        # create_event actually needs the customer's email.
        assert len(session_factory_calls) == 1

        now = datetime(2026, 7, 6, 9, 0, tzinfo=timezone.utc)
        appointment = Appointment(
            id=uuid.uuid4(),
            service_call_id=uuid.uuid4(),
            technician_id=tech_id,
            customer_id=customer_id,
            time_range=TimeRange(now, datetime(2026, 7, 6, 10, 0, tzinfo=timezone.utc)),
            status=AppointmentStatus.SCHEDULED,
            details=None,
            created_at=now,
            updated_at=now,
        )
        adapter.create_event(appointment, AppointmentContext(customer_name="Ada"))

        # A second session_factory() call happened lazily inside attendee_email, proving the
        # Task 1 factory resolver was actually exercised with a real session_factory.
        assert len(session_factory_calls) == 2
        _cal_id, body = fake_client.insert_event.call_args[0]
        assert body["attendees"] == [
            {"email": "customer@example.com", "responseStatus": "needsAction"}
        ]


# ---------------------------------------------------------------------------
# Integration test against real Postgres
# ---------------------------------------------------------------------------

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

        from sqlalchemy import create_engine as _ce
        engine = _ce(url)
        yield engine
        engine.dispose()
        del os.environ["DATABASE_URL"]


@pytest.fixture
def pg_session(pg_engine):
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=pg_engine, expire_on_commit=False)
    with Session() as sess:
        with sess.begin():
            sess.begin_nested()
            yield sess
            sess.rollback()


class TestCalendarResolverIntegration:
    def test_connected_technician_resolves_to_google_adapter(self, pg_session):
        from cryptography.fernet import Fernet

        from fsm.google_calendar.adapters.repositories import SqlAlchemyCalendarConnectionRepository
        from fsm.google_calendar.adapters.token_cipher import FernetTokenCipher
        from fsm.google_calendar.domain.connection import CalendarConnection

        real_key = Fernet.generate_key().decode()
        settings = Settings(
            database_url="postgresql+psycopg://x:x@localhost/x",
            google_client_id="integration-client-id",
            google_client_secret=SecretStr("integration-secret"),
            fsm_token_key=SecretStr(real_key),
        )

        tech_id = uuid.uuid4()
        fsm_cal_id = "cal-integration-123"
        encrypted_token = FernetTokenCipher(real_key).encrypt("real-refresh-token")

        repo = SqlAlchemyCalendarConnectionRepository(pg_session)
        conn = CalendarConnection(
            technician_id=tech_id,
            fsm_calendar_id=fsm_cal_id,
            status=CalendarConnectionStatus.CONNECTED,
        )
        repo.add(conn, encrypted_token)
        pg_session.flush()

        # Provide the same session as a context-manager-compatible factory so the
        # resolver sees the uncommitted test data in the current transaction.
        class _SameSessionFactory:
            def __call__(self):
                return _SameSessionContext(pg_session)

        class _SameSessionContext:
            def __init__(self, session):
                self._session = session

            def __enter__(self):
                return self._session

            def __exit__(self, *_):
                pass

        fake_client = MagicMock()
        factory_calls = []

        def fake_client_factory(**kwargs):
            factory_calls.append(kwargs)
            return fake_client

        resolver = build_calendar_resolver(
            session_factory=_SameSessionFactory(),
            settings=settings,
            client_factory=fake_client_factory,
        )
        result = resolver(tech_id)

        assert isinstance(result, GoogleCalendarAdapter)
        assert result._calendar_id == fsm_cal_id
        assert len(factory_calls) == 1
        assert factory_calls[0]["refresh_token"] == "real-refresh-token"

    def test_unconnected_technician_resolves_to_null(self, pg_session):
        from cryptography.fernet import Fernet

        real_key = Fernet.generate_key().decode()
        settings = Settings(
            database_url="postgresql+psycopg://x:x@localhost/x",
            google_client_id="id",
            google_client_secret=SecretStr("secret"),
            fsm_token_key=SecretStr(real_key),
        )

        class _SameSessionFactory:
            def __call__(self):
                return _SameSessionContext(pg_session)

        class _SameSessionContext:
            def __init__(self, session):
                self._session = session

            def __enter__(self):
                return self._session

            def __exit__(self, *_):
                pass

        resolver = build_calendar_resolver(
            session_factory=_SameSessionFactory(),
            settings=settings,
        )
        result = resolver(uuid.uuid4())
        assert isinstance(result, NullCalendarPort)
