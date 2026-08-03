import pytest
from sqlalchemy import text
from testcontainers.postgres import PostgresContainer

from fsm.core.db import session_factory
from fsm.platform import db
from fsm.platform.config import Settings
from fsm.platform.db import MAX_OVERFLOW, POOL_SIZE, create_engine_from_settings


@pytest.fixture(scope="module")
def settings():
    with PostgresContainer("pgvector/pgvector:pg16", driver="psycopg") as postgres:
        yield Settings(database_url=postgres.get_connection_url(), app_env="test")


def test_engine_connects_and_session_executes(settings):
    engine = create_engine_from_settings(settings)
    factory = session_factory(engine)

    with factory() as session:
        result = session.execute(text("SELECT 1")).scalar_one()

    assert result == 1


def test_engine_is_built_at_this_deployments_pool_sizing(monkeypatch):
    """The pool arithmetic is platform's: three role processes share one Postgres."""
    recorded = {}

    def _record(database_url, *, pool_size, max_overflow):
        recorded.update(url=database_url, pool_size=pool_size, max_overflow=max_overflow)

    monkeypatch.setattr(db, "build_engine", _record)
    create_engine_from_settings(
        Settings(database_url="postgresql+psycopg://u:p@localhost:5432/fsm", app_env="test")
    )

    assert recorded == {
        "url": "postgresql+psycopg://u:p@localhost:5432/fsm",
        "pool_size": POOL_SIZE,
        "max_overflow": MAX_OVERFLOW,
    }
