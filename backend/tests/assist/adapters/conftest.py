"""Shared fixtures for adapter tests that need a real, migrated Postgres."""
import os
import pathlib

import pytest
from sqlalchemy import create_engine


@pytest.fixture(scope="module")
def pg_engine():
    from alembic import command as alembic_command
    from alembic.config import Config as AlembicConfig
    from testcontainers.postgres import PostgresContainer

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
        yield engine
        engine.dispose()
        del os.environ["DATABASE_URL"]
