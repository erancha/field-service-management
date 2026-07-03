"""Shared test configuration.

Keeps the suite hermetic with respect to a developer's local ``backend/.env``. ``Settings``
auto-loads ``.env`` from the working directory, so a real ``backend/.env`` (for example one created
by ``scripts/init-env.sh``, which fills in ``FSM_TOKEN_KEY`` and ``SESSION_SECRET``) would otherwise
bleed configured values into tests that construct ``Settings`` to represent an *unconfigured*
environment — making assertions like "calendar login returns 503 when unconfigured" pass or fail
depending on whether the developer has set up their .env.
"""
from __future__ import annotations

import os

import pytest

from fsm.platform.config import Settings, get_settings

# SMTP variables that, if present in the developer's .env, would make integration tests deliver real
# notification email. Emptied before any Settings is built (see pytest_configure).
_SMTP_ENV_VARS = ("SMTP_HOST", "SMTP_USER", "SMTP_PASS", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM")


def pytest_configure(config: pytest.Config) -> None:
    """Force SMTP unconfigured for the whole session so no test delivers real email.

    The function-scoped fixture below only protects Settings built inside a test; the cached
    ``get_settings()`` that ``create_app`` uses in the integration suite is populated by a
    module-scoped app fixture before any function fixture runs, so it would otherwise read the
    developer's real SMTP credentials from ``.env``. Setting the SMTP variables empty here (env
    vars take precedence over ``.env``) and clearing the cache guarantees the logging email sender
    is used instead. Booking flows that resolve a real recipient would otherwise send mail — the
    integration tests seed ``@example.com`` users, whose bounces flood the sender's inbox.
    """
    for var in _SMTP_ENV_VARS:
        os.environ[var] = ""
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _settings_ignore_dotenv(monkeypatch):
    """Disable ``.env`` loading for every ``Settings`` constructed during a test."""
    monkeypatch.setitem(Settings.model_config, "env_file", None)
