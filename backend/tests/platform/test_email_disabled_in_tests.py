"""Guardrail: the test suite must never deliver real notification email.

``create_app`` loads ``Settings`` from the developer's ``backend/.env``, which may carry live SMTP
credentials. Booking flows resolve their recipients from seeded ``@example.com`` users and would
otherwise send mail whose bounces flood the sender's inbox. ``pytest_configure`` empties the SMTP
variables for the whole session; these tests fail loudly if that protection ever regresses.
"""
from __future__ import annotations

import os

from fsm.notifications.adapters.smtp_email_sender import LoggingEmailSender
from fsm.platform.config import Settings
from fsm.platform.notifications_factory import build_notifications

_DUMMY_DB_URL = "postgresql+psycopg://user:pass@localhost:5432/fsm_test"


class _StubSession:
    """Placeholder session; the notifications factory only stores it, never queries it here."""


def test_smtp_env_emptied_for_session() -> None:
    for var in ("SMTP_HOST", "SMTP_USER", "SMTP_PASS", "SMTP_FROM"):
        assert os.environ.get(var) == "", f"{var} must be emptied so tests never send real email"


def test_settings_report_smtp_unconfigured() -> None:
    settings = Settings(database_url=_DUMMY_DB_URL)
    assert not settings.smtp_host
    assert not settings.smtp_sender_address


def test_notifications_factory_falls_back_to_logging_sender() -> None:
    port = build_notifications(session=_StubSession(), settings=Settings(database_url=_DUMMY_DB_URL))
    assert isinstance(port._email_sender, LoggingEmailSender)
