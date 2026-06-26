"""Integration tests verifying that holiday dates are excluded from availability slots.

Seeds a holiday on a working day (Sunday in the Israeli schedule), then checks that
GET /availability returns zero slots on that day but normal slots on adjacent working days.
"""
from __future__ import annotations

import os
import pathlib
import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from testcontainers.postgres import PostgresContainer

from fsm.platform.app import create_app
from fsm.scheduling.adapters.holiday_repository import SqlAlchemyHolidayRepository
from fsm.scheduling.domain.holiday import Holiday


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

# 2025-01-05 is a Sunday — a working day in the default Israeli schedule (Sun-Thu).
_HOLIDAY_DATE = date(2025, 7, 6)   # Sunday
_ADJACENT_BEFORE = date(2025, 7, 3)  # Thursday — working day
_ADJACENT_AFTER = date(2025, 7, 7)   # Monday — working day


@pytest.fixture(scope="module", autouse=True)
def seed_holiday(pg_session_factory):
    """Insert the test holiday into the DB before any test in this module runs."""
    with pg_session_factory() as session:
        with session.begin():
            repo = SqlAlchemyHolidayRepository(session)
            repo.upsert_many([Holiday(date=_HOLIDAY_DATE, name="Test Holiday")])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_no_slots_on_holiday_date(client):
    tech_id = uuid.uuid4()
    response = client.get(
        "/api/availability",
        params={
            "technician_id": str(tech_id),
            "date_from": _HOLIDAY_DATE.isoformat(),
            "date_to": _HOLIDAY_DATE.isoformat(),
            "slot_minutes": 60,
            "tz": "Asia/Jerusalem",
        },
    )
    assert response.status_code == 200
    assert response.json()["slots"] == []


def test_normal_slots_on_adjacent_working_days(client):
    tech_id = uuid.uuid4()
    response = client.get(
        "/api/availability",
        params={
            "technician_id": str(tech_id),
            "date_from": _ADJACENT_BEFORE.isoformat(),
            "date_to": _ADJACENT_AFTER.isoformat(),
            "slot_minutes": 60,
            "tz": "Asia/Jerusalem",
        },
    )
    assert response.status_code == 200
    slots = response.json()["slots"]
    # 2 working days × 8 slots = 16 slots (holiday in the middle excluded)
    assert len(slots) == 16
