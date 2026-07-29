import pytest
from sqlalchemy import text
from testcontainers.postgres import PostgresContainer

from fsm.platform.config import Settings
from fsm.platform.db import create_engine_from_settings, session_factory


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
