"""Integration tests for the working-hours endpoints.

Tests:
- PUT /technicians/{id}/working-hours stores a Mon–Fri schedule.
- GET /technicians/{id}/working-hours returns it.
- GET /availability returns slots on Friday and none on Sunday for a Mon–Fri schedule.
- Invalid window (start >= end) → 400.
- Duplicate weekday in payload → 400.
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


@pytest.fixture(scope="module")
def client(pg_session_factory):
    app = create_app(session_factory=pg_session_factory)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Mon=0 … Fri=4 (Python weekday convention)
_MON_FRI_WINDOWS = [
    {"weekday": wd, "start": "08:00:00", "end": "16:00:00"} for wd in range(5)
]

# 2025-07-14 is a Monday. The week Mon 2025-07-14 … Sun 2025-07-20.
# With Mon-Fri schedule: slots on Mon-Fri, none on Sat-Sun.
_MONDAY = date(2025, 7, 14)
_FRIDAY = date(2025, 7, 18)
_SATURDAY = date(2025, 7, 19)
_SUNDAY = date(2025, 7, 20)


# ---------------------------------------------------------------------------
# Working-hours CRUD
# ---------------------------------------------------------------------------


def test_put_working_hours_returns_200(client, authenticate):
    tech_id = authenticate(client.app, role=Role.TECHNICIAN)
    resp = client.put(
        f"/api/technicians/{tech_id}/working-hours",
        json={"windows": _MON_FRI_WINDOWS},
    )
    assert resp.status_code == 200


def test_get_working_hours_returns_stored_schedule(client, authenticate):
    tech_id = authenticate(client.app, role=Role.TECHNICIAN)
    client.put(
        f"/api/technicians/{tech_id}/working-hours",
        json={"windows": _MON_FRI_WINDOWS},
    )

    resp = client.get(f"/api/technicians/{tech_id}/working-hours")
    assert resp.status_code == 200

    stored_weekdays = {w["weekday"] for w in resp.json()["windows"]}
    assert stored_weekdays == {0, 1, 2, 3, 4}


def test_get_working_hours_returns_default_when_unset(client, authenticate):
    tech_id = authenticate(client.app, role=Role.TECHNICIAN)
    resp = client.get(f"/api/technicians/{tech_id}/working-hours")
    assert resp.status_code == 200

    # Default: Sun–Thu (weekdays 6, 0, 1, 2, 3)
    stored_weekdays = {w["weekday"] for w in resp.json()["windows"]}
    assert stored_weekdays == {6, 0, 1, 2, 3}


def test_put_invalid_window_start_gte_end_returns_400(client, authenticate):
    tech_id = authenticate(client.app, role=Role.TECHNICIAN)
    resp = client.put(
        f"/api/technicians/{tech_id}/working-hours",
        json={"windows": [{"weekday": 0, "start": "17:00:00", "end": "09:00:00"}]},
    )
    assert resp.status_code == 400


def test_put_duplicate_weekday_returns_400(client, authenticate):
    tech_id = authenticate(client.app, role=Role.TECHNICIAN)
    resp = client.put(
        f"/api/technicians/{tech_id}/working-hours",
        json={
            "windows": [
                {"weekday": 0, "start": "08:00:00", "end": "16:00:00"},
                {"weekday": 0, "start": "09:00:00", "end": "17:00:00"},
            ]
        },
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Availability reflects per-technician schedule
# ---------------------------------------------------------------------------


def test_availability_slots_on_friday_with_mon_fri_schedule(client, authenticate):
    tech_id = authenticate(client.app, role=Role.TECHNICIAN)
    client.put(
        f"/api/technicians/{tech_id}/working-hours",
        json={"windows": _MON_FRI_WINDOWS},
    )

    resp = client.get(
        "/api/availability",
        params={
            "technician_id": str(tech_id),
            "date_from": _FRIDAY.isoformat(),
            "date_to": _FRIDAY.isoformat(),
            "slot_minutes": 60,
            "tz": "Asia/Jerusalem",
        },
    )
    assert resp.status_code == 200
    # 08:00–16:00 = 8 one-hour slots
    assert len(resp.json()["slots"]) == 8


def test_availability_no_slots_on_sunday_with_mon_fri_schedule(client, authenticate):
    tech_id = authenticate(client.app, role=Role.TECHNICIAN)
    client.put(
        f"/api/technicians/{tech_id}/working-hours",
        json={"windows": _MON_FRI_WINDOWS},
    )

    resp = client.get(
        "/api/availability",
        params={
            "technician_id": str(tech_id),
            "date_from": _SUNDAY.isoformat(),
            "date_to": _SUNDAY.isoformat(),
            "slot_minutes": 60,
            "tz": "Asia/Jerusalem",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["slots"] == []
