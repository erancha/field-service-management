"""Integration tests: GET /availability subtracts per-technician Google free/busy (§5).

Spec §5: slot = working hours − holidays − private free/busy − existing FSM appointments.
These tests exercise only the free/busy leg. The availability endpoint must:
- Subtract busy intervals reported by the technician's CalendarPort from proposed slots.
- Fall back to NullCalendarPort (full slot set) for unconnected / unconfigured technicians.
- Degrade to NullCalendarPort (full slot set, no 500) when the resolver itself raises.

The injectable seam app.state.calendar_client_factory_override is used here in the same
way the calendar-connect tests use it, so no real Google credentials are needed.
"""
from __future__ import annotations

import os
import pathlib
import uuid
from datetime import date, datetime, timezone

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from testcontainers.postgres import PostgresContainer

from fsm.calendar.adapters.repositories import SqlAlchemyCalendarConnectionRepository
from fsm.calendar.adapters.token_cipher import FernetTokenCipher
from fsm.calendar.domain.connection import CalendarConnection, CalendarConnectionStatus
from fsm.platform.app import create_app
from fsm.platform.config import Settings


# ---------------------------------------------------------------------------
# Module-scoped container + migrated engine
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pg_session_factory():
    from alembic import command as alembic_command
    from alembic.config import Config as AlembicConfig

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
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        yield factory
        engine.dispose()
        del os.environ["DATABASE_URL"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# 2025-01-05 is a Sunday — a working day in the default Israeli schedule (Sun-Thu).
_WORKING_DATE = date(2025, 1, 5)


def _configured_settings(pg_url: str, token_key: str) -> Settings:
    return Settings(
        database_url=pg_url,
        google_client_id="test-client-id",
        google_client_secret="test-client-secret",
        fsm_token_key=token_key,
    )


def _unconfigured_settings(pg_url: str) -> Settings:
    return Settings(
        database_url=pg_url,
        google_client_id=None,
        google_client_secret=None,
        fsm_token_key=None,
    )


def _store_connected_technician(pg_session_factory, tech_id: uuid.UUID, token_key: str) -> str:
    """Insert a CONNECTED CalendarConnection for tech_id; return the calendar_id used."""
    encrypted = FernetTokenCipher(token_key).encrypt("refresh-token-test")
    cal_id = f"cal-{tech_id}"
    with pg_session_factory() as session:
        with session.begin():
            repo = SqlAlchemyCalendarConnectionRepository(session)
            conn = CalendarConnection(
                technician_id=tech_id,
                fsm_calendar_id=cal_id,
                status=CalendarConnectionStatus.CONNECTED,
            )
            repo.add(conn, encrypted)
    return cal_id


class _FakeCalendarClient:
    """Minimal GoogleCalendarClient stub whose query_busy returns a configurable busy list."""

    def __init__(self, busy_intervals: list[tuple[datetime, datetime]]) -> None:
        self._busy = busy_intervals

    def query_busy(
        self,
        calendar_id: str,
        time_min: datetime,
        time_max: datetime,
    ) -> list[tuple[datetime, datetime]]:
        return list(self._busy)


# ---------------------------------------------------------------------------
# 1. Free/busy is subtracted
# ---------------------------------------------------------------------------


def test_busy_interval_excluded_from_slots(pg_session_factory, authenticate):
    """A connected technician's 09:00–10:00 busy block is excluded from availability."""
    token_key = Fernet.generate_key().decode()
    tech_id = uuid.uuid4()
    _store_connected_technician(pg_session_factory, tech_id, token_key)

    # Busy: 09:00–10:00 UTC+2 (Asia/Jerusalem on 2025-01-05 is UTC+2)
    # Working hours: 09:00–17:00 local → 8 slots normally; minus the 09:00 slot = 7.
    busy_start = datetime(2025, 1, 5, 7, 0, tzinfo=timezone.utc)   # 09:00 local
    busy_end = datetime(2025, 1, 5, 8, 0, tzinfo=timezone.utc)     # 10:00 local

    fake_client = _FakeCalendarClient([(busy_start, busy_end)])

    settings = _configured_settings(os.environ["DATABASE_URL"], token_key)
    app = create_app(session_factory=pg_session_factory, settings=settings)
    authenticate(app)
    # Inject the seam: the resolver calls client_factory(refresh_token=...) to build a client.
    app.state.calendar_client_factory_override = lambda **kw: fake_client
    client = TestClient(app)

    resp = client.get(
        "/api/availability",
        params={
            "technician_id": str(tech_id),
            "date_from": _WORKING_DATE.isoformat(),
            "date_to": _WORKING_DATE.isoformat(),
            "slot_minutes": 60,
            "tz": "Asia/Jerusalem",
        },
    )

    assert resp.status_code == 200
    slots = resp.json()["slots"]
    # 8 normal slots minus the 09:00–10:00 busy block = 7
    assert len(slots) == 7
    # The 09:00 slot must be absent
    starts = [s["start"] for s in slots]
    assert not any("09:00" in s or "07:00" in s for s in starts), (
        "09:00 local (07:00 UTC) slot should have been excluded"
    )


def test_no_busy_returns_full_slot_set(pg_session_factory, authenticate):
    """A connected technician with no busy intervals gets the full 8-slot day."""
    token_key = Fernet.generate_key().decode()
    tech_id = uuid.uuid4()
    _store_connected_technician(pg_session_factory, tech_id, token_key)

    fake_client = _FakeCalendarClient([])  # no busy

    settings = _configured_settings(os.environ["DATABASE_URL"], token_key)
    app = create_app(session_factory=pg_session_factory, settings=settings)
    authenticate(app)
    app.state.calendar_client_factory_override = lambda **kw: fake_client
    client = TestClient(app)

    resp = client.get(
        "/api/availability",
        params={
            "technician_id": str(tech_id),
            "date_from": _WORKING_DATE.isoformat(),
            "date_to": _WORKING_DATE.isoformat(),
            "slot_minutes": 60,
            "tz": "Asia/Jerusalem",
        },
    )

    assert resp.status_code == 200
    assert len(resp.json()["slots"]) == 8


# ---------------------------------------------------------------------------
# 2. Unconnected technician / unconfigured Google → NullCalendarPort fallback
# ---------------------------------------------------------------------------


def test_unconnected_technician_returns_full_slots(pg_session_factory, authenticate):
    """An unconnected technician gets the full slot set — NullCalendarPort path."""
    settings = _configured_settings(os.environ["DATABASE_URL"], Fernet.generate_key().decode())
    app = create_app(session_factory=pg_session_factory, settings=settings)
    authenticate(app)
    client = TestClient(app)

    # tech_id has no CalendarConnection row
    resp = client.get(
        "/api/availability",
        params={
            "technician_id": str(uuid.uuid4()),
            "date_from": _WORKING_DATE.isoformat(),
            "date_to": _WORKING_DATE.isoformat(),
            "slot_minutes": 60,
            "tz": "Asia/Jerusalem",
        },
    )

    assert resp.status_code == 200
    assert len(resp.json()["slots"]) == 8


def test_unconfigured_google_returns_full_slots(pg_session_factory, authenticate):
    """When Google is not configured the endpoint degrades to NullCalendarPort."""
    settings = _unconfigured_settings(os.environ["DATABASE_URL"])
    app = create_app(session_factory=pg_session_factory, settings=settings)
    authenticate(app)
    client = TestClient(app)

    resp = client.get(
        "/api/availability",
        params={
            "technician_id": str(uuid.uuid4()),
            "date_from": _WORKING_DATE.isoformat(),
            "date_to": _WORKING_DATE.isoformat(),
            "slot_minutes": 60,
            "tz": "Asia/Jerusalem",
        },
    )

    assert resp.status_code == 200
    assert len(resp.json()["slots"]) == 8


# ---------------------------------------------------------------------------
# 3. Resolver failure degrades gracefully — never 500
# ---------------------------------------------------------------------------


def test_resolver_failure_degrades_to_full_slots(pg_session_factory, authenticate):
    """If the client factory raises, availability returns slots rather than 500."""
    token_key = Fernet.generate_key().decode()
    tech_id = uuid.uuid4()
    _store_connected_technician(pg_session_factory, tech_id, token_key)

    def _exploding_factory(**kw):
        raise RuntimeError("Google is down")

    settings = _configured_settings(os.environ["DATABASE_URL"], token_key)
    app = create_app(session_factory=pg_session_factory, settings=settings)
    authenticate(app)
    app.state.calendar_client_factory_override = _exploding_factory
    client = TestClient(app)

    resp = client.get(
        "/api/availability",
        params={
            "technician_id": str(tech_id),
            "date_from": _WORKING_DATE.isoformat(),
            "date_to": _WORKING_DATE.isoformat(),
            "slot_minutes": 60,
            "tz": "Asia/Jerusalem",
        },
    )

    assert resp.status_code == 200
    # Should fall back to NullCalendarPort and return the full 8 slots
    assert len(resp.json()["slots"]) == 8
