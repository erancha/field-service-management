"""Shared test configuration.

Keeps the suite hermetic with respect to a developer's local `backend/.env`. `Settings`
auto-loads `.env` from the working directory, so a real `backend/.env` (for example one created
by `scripts/init-env.sh`, which fills in `FSM_TOKEN_KEY` and `SESSION_SECRET`) would otherwise
bleed configured values into tests that construct `Settings` to represent an unconfigured
environment — making assertions like "calendar login returns 503 when unconfigured" pass or fail
depending on whether the developer has set up their .env.
"""
from __future__ import annotations

import os
import pathlib

import pytest

from fsm.platform.config import Settings, get_settings

# SMTP variables that, if present in the developer's .env, would make integration tests deliver real
# notification email. Emptied before any Settings is built (see pytest_configure).
_SMTP_ENV_VARS = ("SMTP_HOST", "SMTP_USER", "SMTP_PASS", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM")

# AI provider keys that, if present in the developer's .env, would let a test build a Settings that
# claims a provider is configured (or spend real API quota if the KB code path is ever exercised).
# Emptied before any Settings is built (see pytest_configure), same rationale as _SMTP_ENV_VARS.
_ASSIST_ENV_VARS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY")


def pytest_configure(config: pytest.Config) -> None:
    """Force SMTP and the AI provider keys unconfigured for the whole session.

    The function-scoped fixture below only protects Settings built inside a test; the cached
    `get_settings()` that `create_app` uses in the integration suite is populated by a
    module-scoped app fixture before any function fixture runs, so it would otherwise read the
    developer's real SMTP credentials (and AI provider keys) from `.env`. Setting these
    variables empty here (env vars take precedence over `.env`) and clearing the cache
    guarantees the logging email sender is used, and the knowledge base stays disabled, instead.
    Booking flows that resolve a real recipient would otherwise send mail — the integration
    tests seed `@example.com` users, whose bounces flood the sender's inbox.
    """
    for var in (*_SMTP_ENV_VARS, *_ASSIST_ENV_VARS):
        os.environ[var] = ""
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _settings_ignore_dotenv(monkeypatch):
    """Disable `.env` loading for every `Settings` constructed during a test."""
    monkeypatch.setitem(Settings.model_config, "env_file", None)


@pytest.fixture(scope="module")
def pg_engine():
    """A real, Alembic-migrated Postgres, shared by every test module that requests it."""
    from alembic import command as alembic_command
    from alembic.config import Config as AlembicConfig
    from sqlalchemy import create_engine
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("pgvector/pgvector:pg16", driver="psycopg") as pg:
        url = pg.get_connection_url()
        os.environ["DATABASE_URL"] = url

        cfg = AlembicConfig()
        cfg.set_main_option(
            "script_location",
            str(pathlib.Path(__file__).parents[1] / "alembic"),
        )
        cfg.set_main_option("sqlalchemy.url", url)
        alembic_command.upgrade(cfg, "head")

        engine = create_engine(url)
        yield engine
        engine.dispose()
        del os.environ["DATABASE_URL"]
