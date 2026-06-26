"""Shared test configuration.

Keeps the suite hermetic with respect to a developer's local ``backend/.env``. ``Settings``
auto-loads ``.env`` from the working directory, so a real ``backend/.env`` (for example one created
by ``scripts/init-env.sh``, which fills in ``FSM_TOKEN_KEY`` and ``SESSION_SECRET``) would otherwise
bleed configured values into tests that construct ``Settings`` to represent an *unconfigured*
environment — making assertions like "calendar login returns 503 when unconfigured" pass or fail
depending on whether the developer has set up their .env.
"""
from __future__ import annotations

import pytest

from fsm.platform.config import Settings


@pytest.fixture(autouse=True)
def _settings_ignore_dotenv(monkeypatch):
    """Disable ``.env`` loading for every ``Settings`` constructed during a test."""
    monkeypatch.setitem(Settings.model_config, "env_file", None)
