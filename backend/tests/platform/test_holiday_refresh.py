"""Integration tests for refresh_holidays against real Postgres.

Injects a fake reader_factory to avoid any network calls.
"""
from __future__ import annotations

import os
import pathlib
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from testcontainers.postgres import PostgresContainer

from fsm.platform.config import Settings
from fsm.platform.holiday_refresh import refresh_holidays
from fsm.scheduling.adapters.holiday_repository import SqlAlchemyHolidayRepository


# ---------------------------------------------------------------------------
# Module-scoped container + migrated engine
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pg_engine():
    from alembic import command as alembic_command
    from alembic.config import Config as AlembicConfig

    with PostgresContainer("pgvector/pgvector:pg16", driver="psycopg") as pg:
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


@pytest.fixture
def pg_session_factory(pg_engine):
    return sessionmaker(bind=pg_engine, expire_on_commit=False)


def _make_settings(**overrides) -> Settings:
    base = dict(
        database_url="postgresql+psycopg://ignored:ignored@localhost/ignored",
        app_env="test",
        google_api_key="fake-api-key",
        holiday_calendar_id="en.usa#holiday@group.v.calendar.google.com",
        holiday_refresh_years_ahead=1,
    )
    base.update(overrides)
    return Settings(**base)


def _fake_reader_factory(holidays: list[tuple[date, str]]):
    """Return a reader_factory that ignores the api_key and returns canned holidays."""
    class _FakeReader:
        def list_holidays(self, calendar_id, time_min, time_max):
            return holidays

    def factory(api_key):
        return _FakeReader()

    return factory


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_refresh_upserts_holidays_and_returns_count(pg_session_factory):
    canned = [
        (date(2040, 1, 1), "New Year"),
        (date(2040, 7, 4), "Independence Day"),
    ]
    settings = _make_settings()
    count = refresh_holidays(
        pg_session_factory,
        settings,
        reader_factory=_fake_reader_factory(canned),
        today=date(2040, 1, 1),
    )

    assert count == 2

    with pg_session_factory() as session:
        repo = SqlAlchemyHolidayRepository(session)
        result = repo.list_between(date(2040, 1, 1), date(2040, 12, 31))

    assert date(2040, 1, 1) in result
    assert date(2040, 7, 4) in result


def test_refresh_is_noop_when_credentials_missing(pg_session_factory):
    settings = _make_settings(google_api_key=None, holiday_calendar_id=None)
    count = refresh_holidays(pg_session_factory, settings, today=date(2041, 1, 1))
    assert count == 0


def test_refresh_is_noop_when_only_api_key_missing(pg_session_factory):
    settings = _make_settings(google_api_key=None)
    count = refresh_holidays(pg_session_factory, settings, today=date(2042, 1, 1))
    assert count == 0


def test_refresh_swallows_reader_error_and_preserves_cache(pg_session_factory):
    # Seed one holiday first
    seed = [(date(2043, 5, 27), "Memorial Day")]
    settings = _make_settings()
    refresh_holidays(
        pg_session_factory,
        settings,
        reader_factory=_fake_reader_factory(seed),
        today=date(2043, 1, 1),
    )

    # Now run with a reader that raises
    class _FailingReader:
        def list_holidays(self, *_args, **_kwargs):
            raise RuntimeError("network error")

    def failing_factory(api_key):
        return _FailingReader()

    count = refresh_holidays(
        pg_session_factory,
        settings,
        reader_factory=failing_factory,
        today=date(2043, 1, 1),
    )

    assert count == 0  # error swallowed, returns 0

    # Cache is still intact
    with pg_session_factory() as session:
        repo = SqlAlchemyHolidayRepository(session)
        result = repo.list_between(date(2043, 1, 1), date(2043, 12, 31))
    assert date(2043, 5, 27) in result
