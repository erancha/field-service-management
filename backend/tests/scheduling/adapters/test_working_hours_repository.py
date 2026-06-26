"""Integration tests for SqlAlchemyWorkingHoursRepository against real Postgres.

A Postgres 16 container is started once per module with Alembic migrations applied.
Each test runs inside a rolled-back session so rows do not bleed between tests.
"""
from __future__ import annotations

import os
import pathlib
import uuid
from datetime import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from testcontainers.postgres import PostgresContainer

from fsm.scheduling.adapters.working_hours_repository import SqlAlchemyWorkingHoursRepository
from fsm.scheduling.domain.working_hours import DailyHours, WeeklyWorkingHours


# ---------------------------------------------------------------------------
# Module-scoped container + migrated engine
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pg_engine():
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
        yield engine
        engine.dispose()
        del os.environ["DATABASE_URL"]


@pytest.fixture
def session(pg_engine):
    factory = sessionmaker(bind=pg_engine, expire_on_commit=False)
    with factory() as s:
        yield s
        s.rollback()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MON_FRI = WeeklyWorkingHours(
    windows=tuple(
        DailyHours(weekday=wd, start=time(8, 0), end=time(16, 0))
        for wd in range(5)  # Mon=0 … Fri=4
    )
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_get_returns_default_when_unset(session):
    tech_id = uuid.uuid4()
    repo = SqlAlchemyWorkingHoursRepository(session)

    result = repo.get_for_technician(tech_id)

    assert result == WeeklyWorkingHours.default()


def test_set_and_get_round_trip(session):
    tech_id = uuid.uuid4()
    repo = SqlAlchemyWorkingHoursRepository(session)

    repo.set_for_technician(tech_id, _MON_FRI)
    result = repo.get_for_technician(tech_id)

    assert {(dh.weekday, dh.start, dh.end) for dh in result.windows} == {
        (dh.weekday, dh.start, dh.end) for dh in _MON_FRI.windows
    }


def test_set_replaces_existing_rows(session):
    tech_id = uuid.uuid4()
    repo = SqlAlchemyWorkingHoursRepository(session)

    # First set: Mon–Fri 08:00–16:00
    repo.set_for_technician(tech_id, _MON_FRI)

    # Second set: only Monday 10:00–14:00
    mon_only = WeeklyWorkingHours(windows=(DailyHours(weekday=0, start=time(10, 0), end=time(14, 0)),))
    repo.set_for_technician(tech_id, mon_only)

    result = repo.get_for_technician(tech_id)

    # Should contain exactly one window (Monday only), not the original five.
    assert len(result.windows) == 1
    assert result.windows[0].weekday == 0
    assert result.windows[0].start == time(10, 0)
    assert result.windows[0].end == time(14, 0)


def test_per_technician_isolation(session):
    tech_a = uuid.uuid4()
    tech_b = uuid.uuid4()
    repo = SqlAlchemyWorkingHoursRepository(session)

    repo.set_for_technician(tech_a, _MON_FRI)

    # tech_b has no configuration; must get the default.
    result_b = repo.get_for_technician(tech_b)
    assert result_b == WeeklyWorkingHours.default()

    # tech_a's configuration must be unaffected.
    result_a = repo.get_for_technician(tech_a)
    assert len(result_a.windows) == 5


def test_timezone_upsert_round_trip(session):
    tech_id = uuid.uuid4()
    repo = SqlAlchemyWorkingHoursRepository(session)

    repo.set_timezone(tech_id, "Europe/London")
    assert repo.get_timezone(tech_id) == "Europe/London"

    # Upsert should replace the previous value.
    repo.set_timezone(tech_id, "America/New_York")
    assert repo.get_timezone(tech_id) == "America/New_York"


def test_get_timezone_returns_none_when_unset(session):
    tech_id = uuid.uuid4()
    repo = SqlAlchemyWorkingHoursRepository(session)

    assert repo.get_timezone(tech_id) is None
