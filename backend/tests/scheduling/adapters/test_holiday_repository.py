"""Integration tests for SqlAlchemyHolidayRepository against real Postgres.

A Postgres 16 container is started once per module with Alembic migrations applied.
Each test runs against the same DB — rows from earlier tests persist, but tests use
distinct date ranges to stay independent.
"""
from __future__ import annotations

import os
import pathlib
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from testcontainers.postgres import PostgresContainer

from fsm.scheduling.adapters.holiday_repository import SqlAlchemyHolidayRepository
from fsm.scheduling.domain.holiday import Holiday


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
# Tests
# ---------------------------------------------------------------------------


def test_upsert_and_list_between_returns_dates_in_range(session):
    repo = SqlAlchemyHolidayRepository(session)
    holidays = [
        Holiday(date=date(2030, 1, 1), name="New Year"),
        Holiday(date=date(2030, 7, 4), name="Independence Day"),
        Holiday(date=date(2030, 12, 25), name="Christmas"),
    ]
    repo.upsert_many(holidays)
    session.flush()

    result = repo.list_between(date(2030, 1, 1), date(2030, 7, 4))

    assert date(2030, 1, 1) in result
    assert date(2030, 7, 4) in result
    assert date(2030, 12, 25) not in result


def test_list_between_excludes_out_of_range(session):
    repo = SqlAlchemyHolidayRepository(session)
    repo.upsert_many([
        Holiday(date=date(2031, 3, 15), name="Pi Day"),
        Holiday(date=date(2031, 5, 1), name="Labour Day"),
        Holiday(date=date(2031, 8, 1), name="August Holiday"),
    ])
    session.flush()

    result = repo.list_between(date(2031, 4, 1), date(2031, 7, 31))

    assert date(2031, 5, 1) in result
    assert date(2031, 3, 15) not in result
    assert date(2031, 8, 1) not in result


def test_upsert_is_idempotent_and_updates_name(session):
    repo = SqlAlchemyHolidayRepository(session)
    repo.upsert_many([Holiday(date=date(2032, 6, 19), name="Juneteenth")])
    session.flush()

    # Re-upsert with a new name — must not raise a duplicate-key error
    repo.upsert_many([Holiday(date=date(2032, 6, 19), name="Juneteenth National Independence Day")])
    session.flush()

    result = repo.list_between(date(2032, 6, 19), date(2032, 6, 19))
    assert result == {date(2032, 6, 19)}
