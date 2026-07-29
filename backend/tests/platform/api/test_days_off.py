"""Integration tests for the days-off endpoints and their effect on availability.

Tests:
- POST /technicians/{id}/days-off marks a day off → 201.
- GET /technicians/{id}/days-off lists it.
- GET /availability returns no slots on the day-off date but normal slots on adjacent days.
- DELETE /technicians/{id}/days-off/{date} removes it → 204; slots reappear.
"""
from __future__ import annotations

import os
import pathlib
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from testcontainers.postgres import PostgresContainer

from fsm.platform.app import create_app
from fsm.identity.domain.role import Role


# ---------------------------------------------------------------------------
# Module-scoped container + migrated engine
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pg_session_factory():
    from alembic import command as alembic_command
    from alembic.config import Config as AlembicConfig

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
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        yield factory
        engine.dispose()
        del os.environ["DATABASE_URL"]


@pytest.fixture(scope="module")
def client(pg_session_factory):
    app = create_app(session_factory=pg_session_factory)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Dates — 2025-07-13 is a Sunday (working day in the Israeli Sun-Thu schedule).
# 2025-07-10 (Thu) and 2025-07-14 (Mon) are adjacent working days.
# ---------------------------------------------------------------------------

_DAY_OFF_DATE = date(2025, 7, 13)    # Sunday — working day
_ADJACENT_BEFORE = date(2025, 7, 10)  # Thursday
_ADJACENT_AFTER = date(2025, 7, 14)   # Monday


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_post_day_off_returns_201(client, authenticate):
    tech_id = authenticate(client.app, role=Role.TECHNICIAN)
    resp = client.post(
        f"/api/technicians/{tech_id}/days-off",
        json={"date": _DAY_OFF_DATE.isoformat()},
    )
    assert resp.status_code == 201


def test_post_day_off_idempotent(client, authenticate):
    tech_id = authenticate(client.app, role=Role.TECHNICIAN)
    client.post(f"/api/technicians/{tech_id}/days-off", json={"date": _DAY_OFF_DATE.isoformat()})
    resp = client.post(
        f"/api/technicians/{tech_id}/days-off",
        json={"date": _DAY_OFF_DATE.isoformat()},
    )
    assert resp.status_code == 201


def test_get_days_off_lists_added_date(client, authenticate):
    tech_id = authenticate(client.app, role=Role.TECHNICIAN)
    client.post(f"/api/technicians/{tech_id}/days-off", json={"date": _DAY_OFF_DATE.isoformat()})

    resp = client.get(
        f"/api/technicians/{tech_id}/days-off",
        params={"date_from": _DAY_OFF_DATE.isoformat(), "date_to": _DAY_OFF_DATE.isoformat()},
    )
    assert resp.status_code == 200
    assert _DAY_OFF_DATE.isoformat() in resp.json()["days_off"]


def test_availability_no_slots_on_day_off(client, authenticate):
    tech_id = authenticate(client.app, role=Role.TECHNICIAN)
    client.post(f"/api/technicians/{tech_id}/days-off", json={"date": _DAY_OFF_DATE.isoformat()})

    resp = client.get(
        "/api/availability",
        params={
            "technician_id": str(tech_id),
            "date_from": _DAY_OFF_DATE.isoformat(),
            "date_to": _DAY_OFF_DATE.isoformat(),
            "slot_minutes": 60,
            "tz": "Asia/Jerusalem",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["slots"] == []


def test_availability_normal_slots_on_adjacent_days(client, authenticate):
    tech_id = authenticate(client.app, role=Role.TECHNICIAN)
    client.post(f"/api/technicians/{tech_id}/days-off", json={"date": _DAY_OFF_DATE.isoformat()})

    resp = client.get(
        "/api/availability",
        params={
            "technician_id": str(tech_id),
            "date_from": _ADJACENT_BEFORE.isoformat(),
            "date_to": _ADJACENT_AFTER.isoformat(),
            "slot_minutes": 60,
            "tz": "Asia/Jerusalem",
        },
    )
    assert resp.status_code == 200
    slots = resp.json()["slots"]
    # 2 adjacent working days × 8 slots = 16; the middle (day-off) is excluded.
    assert len(slots) == 16


def test_delete_day_off_returns_204(client, authenticate):
    tech_id = authenticate(client.app, role=Role.TECHNICIAN)
    client.post(f"/api/technicians/{tech_id}/days-off", json={"date": _DAY_OFF_DATE.isoformat()})

    resp = client.delete(f"/api/technicians/{tech_id}/days-off/{_DAY_OFF_DATE.isoformat()}")
    assert resp.status_code == 204


def test_slots_reappear_after_delete(client, authenticate):
    tech_id = authenticate(client.app, role=Role.TECHNICIAN)
    client.post(f"/api/technicians/{tech_id}/days-off", json={"date": _DAY_OFF_DATE.isoformat()})

    # Confirm no slots.
    resp = client.get(
        "/api/availability",
        params={
            "technician_id": str(tech_id),
            "date_from": _DAY_OFF_DATE.isoformat(),
            "date_to": _DAY_OFF_DATE.isoformat(),
            "slot_minutes": 60,
            "tz": "Asia/Jerusalem",
        },
    )
    assert resp.json()["slots"] == []

    # Remove the day-off.
    client.delete(f"/api/technicians/{tech_id}/days-off/{_DAY_OFF_DATE.isoformat()}")

    # Slots should reappear.
    resp = client.get(
        "/api/availability",
        params={
            "technician_id": str(tech_id),
            "date_from": _DAY_OFF_DATE.isoformat(),
            "date_to": _DAY_OFF_DATE.isoformat(),
            "slot_minutes": 60,
            "tz": "Asia/Jerusalem",
        },
    )
    assert resp.status_code == 200
    assert len(resp.json()["slots"]) == 8
