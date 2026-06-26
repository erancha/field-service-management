"""Integration tests for GET /availability/pool — first-available technician pool (§5).

The pool endpoint returns availability slots across all CONNECTED technicians, each
tagged with its technician_id, sorted by start then technician_id. Technicians without
a calendar connection are excluded from the pool.
"""
from __future__ import annotations

import os
import pathlib
import uuid
from datetime import date

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
from fsm.identity.domain.role import Role


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

# 2025-03-02 is a Sunday — a working day in the default Israeli schedule (Sun-Thu).
# 2025-03-07 is a Friday — not a working day.
_DATE_SUNDAY = date(2025, 3, 2)
_DATE_MONDAY = date(2025, 3, 3)


def _store_connected_technician(
    pg_session_factory, tech_id: uuid.UUID, token_key: str
) -> str:
    """Insert a CONNECTED CalendarConnection; return the calendar_id used."""
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


def _unconfigured_settings(pg_url: str) -> Settings:
    """Settings with no Google credentials — resolver falls back to NullCalendarPort."""
    return Settings(
        database_url=pg_url,
        google_client_id=None,
        google_client_secret=None,
        fsm_token_key=None,
    )


def _configured_settings(pg_url: str, token_key: str) -> Settings:
    return Settings(
        database_url=pg_url,
        google_client_id="test-client-id",
        google_client_secret="test-client-secret",
        fsm_token_key=token_key,
    )


# ---------------------------------------------------------------------------
# 1. Two connected technicians — slots from both appear, each tagged correctly
# ---------------------------------------------------------------------------


def test_pool_returns_slots_from_both_connected_technicians(pg_session_factory, authenticate):
    """Slots from two connected technicians are merged, each tagged with its technician_id."""
    token_key = Fernet.generate_key().decode()
    tech_a = uuid.uuid4()
    tech_b = uuid.uuid4()
    _store_connected_technician(pg_session_factory, tech_a, token_key)
    _store_connected_technician(pg_session_factory, tech_b, token_key)

    # Use unconfigured settings so the resolver falls back to NullCalendarPort for all
    # technicians — this test verifies pool aggregation, not free/busy subtraction.
    settings = _unconfigured_settings(os.environ["DATABASE_URL"])
    app = create_app(session_factory=pg_session_factory, settings=settings)
    authenticate(app)
    client = TestClient(app)

    resp = client.get(
        "/api/availability/pool",
        params={
            "date_from": _DATE_SUNDAY.isoformat(),
            "date_to": _DATE_SUNDAY.isoformat(),
            "slot_minutes": 60,
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert "slots" in data
    slots = data["slots"]

    # Each slot must carry a technician_id, start, and end.
    for slot in slots:
        assert "technician_id" in slot
        assert "start" in slot
        assert "end" in slot

    tech_ids_seen = {s["technician_id"] for s in slots}
    assert str(tech_a) in tech_ids_seen
    assert str(tech_b) in tech_ids_seen

    # Each of tech_a and tech_b contributes 8 slots (Sun 09:00–17:00 default schedule).
    tech_a_slots = [s for s in slots if s["technician_id"] == str(tech_a)]
    tech_b_slots = [s for s in slots if s["technician_id"] == str(tech_b)]
    assert len(tech_a_slots) == 8
    assert len(tech_b_slots) == 8

    # Results must be sorted by start (then technician_id for same-start ties).
    starts = [s["start"] for s in slots]
    assert starts == sorted(starts)


# ---------------------------------------------------------------------------
# 2. Technician B has a day off — only A's slots appear on that date
# ---------------------------------------------------------------------------


def test_pool_excludes_day_off_technician(pg_session_factory, authenticate):
    """On a date where B has a day off, only A's slots appear for that date."""
    token_key = Fernet.generate_key().decode()
    tech_a = uuid.uuid4()
    tech_b = uuid.uuid4()
    _store_connected_technician(pg_session_factory, tech_a, token_key)
    _store_connected_technician(pg_session_factory, tech_b, token_key)

    settings = _unconfigured_settings(os.environ["DATABASE_URL"])
    app = create_app(session_factory=pg_session_factory, settings=settings)
    authenticate(app, user_id=tech_b, role=Role.TECHNICIAN)
    client = TestClient(app)

    # Give B a day off on _DATE_SUNDAY.
    client.post(
        f"/api/technicians/{tech_b}/days-off",
        json={"date": _DATE_SUNDAY.isoformat()},
    )

    # Query a two-day range: Sunday (B off) and Monday (both on).
    resp = client.get(
        "/api/availability/pool",
        params={
            "date_from": _DATE_SUNDAY.isoformat(),
            "date_to": _DATE_MONDAY.isoformat(),
            "slot_minutes": 60,
        },
    )

    assert resp.status_code == 200
    slots = resp.json()["slots"]

    # Filter to only slots belonging to the two technicians seeded in this test.
    test_slots = [s for s in slots if s["technician_id"] in (str(tech_a), str(tech_b))]
    sunday_slots = [s for s in test_slots if _DATE_SUNDAY.isoformat() in s["start"]]
    monday_slots = [s for s in test_slots if _DATE_MONDAY.isoformat() in s["start"]]

    # On Sunday only A has slots (B is off); 8 slots for A.
    sunday_tech_ids = {s["technician_id"] for s in sunday_slots}
    assert str(tech_a) in sunday_tech_ids
    assert str(tech_b) not in sunday_tech_ids
    assert len(sunday_slots) == 8

    # On Monday both A and B are on; 16 slots total for the two test technicians.
    monday_tech_ids = {s["technician_id"] for s in monday_slots}
    assert str(tech_a) in monday_tech_ids
    assert str(tech_b) in monday_tech_ids
    assert len(monday_slots) == 16


# ---------------------------------------------------------------------------
# 3. Unconnected technician does not appear in the pool
# ---------------------------------------------------------------------------


def test_pool_excludes_unconnected_technician(pg_session_factory, authenticate):
    """A technician without a calendar connection does not appear in the pool."""
    token_key = Fernet.generate_key().decode()
    connected_tech = uuid.uuid4()
    unconnected_tech = uuid.uuid4()  # no connection row inserted
    _store_connected_technician(pg_session_factory, connected_tech, token_key)

    settings = _unconfigured_settings(os.environ["DATABASE_URL"])
    app = create_app(session_factory=pg_session_factory, settings=settings)
    authenticate(app)
    client = TestClient(app)

    resp = client.get(
        "/api/availability/pool",
        params={
            "date_from": _DATE_SUNDAY.isoformat(),
            "date_to": _DATE_SUNDAY.isoformat(),
            "slot_minutes": 60,
        },
    )

    assert resp.status_code == 200
    tech_ids_seen = {s["technician_id"] for s in resp.json()["slots"]}
    assert str(connected_tech) in tech_ids_seen
    assert str(unconnected_tech) not in tech_ids_seen


# ---------------------------------------------------------------------------
# 4. Empty pool returns {"slots": []}
# ---------------------------------------------------------------------------


def test_pool_returns_200_and_valid_json_shape(pg_session_factory, authenticate):
    """The pool endpoint returns 200 with a valid slots list regardless of pool contents."""
    settings = _unconfigured_settings(os.environ["DATABASE_URL"])
    app = create_app(session_factory=pg_session_factory, settings=settings)
    authenticate(app)
    client = TestClient(app)

    resp = client.get(
        "/api/availability/pool",
        params={
            "date_from": _DATE_SUNDAY.isoformat(),
            "date_to": _DATE_SUNDAY.isoformat(),
            "slot_minutes": 60,
        },
    )

    assert resp.status_code == 200
    assert "slots" in resp.json()


def test_pool_truly_empty_no_connections(authenticate):
    """An isolated container with no calendar connections returns {slots: []}."""
    from alembic import command as alembic_command
    from alembic.config import Config as AlembicConfig

    with PostgresContainer("postgres:16", driver="psycopg") as pg:
        url = pg.get_connection_url()

        # Temporarily override DATABASE_URL so alembic/env.py migrates this container,
        # not whatever the module-scoped fixture may have set.
        prev_db_url = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = url
        try:
            cfg = AlembicConfig()
            cfg.set_main_option(
                "script_location",
                str(pathlib.Path(__file__).parents[3] / "alembic"),
            )
            cfg.set_main_option("sqlalchemy.url", url)
            alembic_command.upgrade(cfg, "head")
        finally:
            if prev_db_url is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = prev_db_url

        engine = create_engine(url)
        factory = sessionmaker(bind=engine, expire_on_commit=False)

        settings = Settings(
            database_url=url,
            google_client_id=None,
            google_client_secret=None,
            fsm_token_key=None,
        )
        app = create_app(session_factory=factory, settings=settings)
        authenticate(app)
        client = TestClient(app)

        resp = client.get(
            "/api/availability/pool",
            params={
                "date_from": _DATE_SUNDAY.isoformat(),
                "date_to": _DATE_SUNDAY.isoformat(),
                "slot_minutes": 60,
            },
        )

        assert resp.status_code == 200
        assert resp.json() == {"slots": []}

        engine.dispose()
