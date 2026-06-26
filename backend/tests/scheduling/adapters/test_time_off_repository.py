"""Integration tests for SqlAlchemyTimeOffRepository against real Postgres.

A Postgres 16 container is started once per module with Alembic migrations applied.
Each test runs inside a rolled-back session so rows do not bleed between tests.
"""
from __future__ import annotations

import os
import pathlib
import uuid
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from testcontainers.postgres import PostgresContainer

from fsm.scheduling.adapters.time_off_repository import SqlAlchemyTimeOffRepository


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


def test_add_and_list_between_returns_date(session):
    tech_id = uuid.uuid4()
    repo = SqlAlchemyTimeOffRepository(session)

    repo.add(tech_id, date(2030, 3, 10))

    result = repo.list_between(tech_id, date(2030, 3, 1), date(2030, 3, 31))
    assert date(2030, 3, 10) in result


def test_add_is_idempotent(session):
    tech_id = uuid.uuid4()
    repo = SqlAlchemyTimeOffRepository(session)

    # Adding the same date twice must not raise a duplicate-key error.
    repo.add(tech_id, date(2030, 4, 15))
    repo.add(tech_id, date(2030, 4, 15))

    result = repo.list_between(tech_id, date(2030, 4, 15), date(2030, 4, 15))
    assert result == {date(2030, 4, 15)}


def test_list_between_excludes_out_of_range(session):
    tech_id = uuid.uuid4()
    repo = SqlAlchemyTimeOffRepository(session)

    repo.add(tech_id, date(2030, 5, 1))   # before range
    repo.add(tech_id, date(2030, 5, 15))  # in range
    repo.add(tech_id, date(2030, 5, 31))  # after range

    result = repo.list_between(tech_id, date(2030, 5, 10), date(2030, 5, 20))

    assert date(2030, 5, 15) in result
    assert date(2030, 5, 1) not in result
    assert date(2030, 5, 31) not in result


def test_list_between_is_per_technician(session):
    tech_a = uuid.uuid4()
    tech_b = uuid.uuid4()
    repo = SqlAlchemyTimeOffRepository(session)

    repo.add(tech_a, date(2030, 6, 10))
    repo.add(tech_b, date(2030, 6, 10))

    result_a = repo.list_between(tech_a, date(2030, 6, 1), date(2030, 6, 30))
    result_b = repo.list_between(tech_b, date(2030, 6, 1), date(2030, 6, 30))

    # Both have the date but queries are isolated by technician_id.
    assert date(2030, 6, 10) in result_a
    assert date(2030, 6, 10) in result_b

    # Tech A's result must not include dates only added for tech_b (use distinct dates to verify).
    repo.add(tech_b, date(2030, 6, 20))
    result_a_2 = repo.list_between(tech_a, date(2030, 6, 1), date(2030, 6, 30))
    assert date(2030, 6, 20) not in result_a_2


def test_remove_deletes_date(session):
    tech_id = uuid.uuid4()
    repo = SqlAlchemyTimeOffRepository(session)

    repo.add(tech_id, date(2030, 7, 4))
    repo.remove(tech_id, date(2030, 7, 4))

    result = repo.list_between(tech_id, date(2030, 7, 1), date(2030, 7, 31))
    assert date(2030, 7, 4) not in result


def test_remove_is_noop_when_absent(session):
    tech_id = uuid.uuid4()
    repo = SqlAlchemyTimeOffRepository(session)

    # Should not raise even if the row does not exist.
    repo.remove(tech_id, date(2030, 8, 1))
