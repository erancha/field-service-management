"""Unit tests for the technician access request alert emailed to the back-office admins."""
from __future__ import annotations

import logging

from fsm.platform.admin_alerts import send_technician_access_requested
from fsm.shared.constants import BRAND
from tests.notifications.fakes import FakeEmailSender, RaisingEmailSender


class FailingForFirstRecipientSender(FakeEmailSender):
    """Raises for the first send, records the rest — exercises per-recipient isolation."""

    def send(self, to: str, subject: str, body: str) -> None:
        if not self.sent and not getattr(self, "_failed", False):
            self._failed = True
            raise RuntimeError("SMTP unavailable")
        super().send(to, subject, body)


def _send(sender, admins) -> None:
    send_technician_access_requested(
        sender,
        admins,
        requester_name="Dana Levi",
        requester_email="dana@example.com",
    )


def test_emails_every_admin_with_requester_details():
    sender = FakeEmailSender()

    _send(sender, frozenset({"admin1@example.com", "admin2@example.com"}))

    assert {m["to"] for m in sender.sent} == {"admin1@example.com", "admin2@example.com"}
    for message in sender.sent:
        assert message["subject"] == f"{BRAND}: Technician access request — Dana Levi"
        assert "Dana Levi" in message["body"]
        assert "dana@example.com" in message["body"]
        assert "back-office" in message["body"]


def test_send_failure_is_logged_and_remaining_admins_still_emailed(caplog):
    sender = FailingForFirstRecipientSender()

    with caplog.at_level(logging.ERROR, logger="fsm.platform.admin_alerts"):
        _send(sender, frozenset({"admin1@example.com", "admin2@example.com"}))

    assert len(sender.sent) == 1
    assert any("Technician access request" in r.getMessage() for r in caplog.records)


def test_all_sends_failing_never_raises(caplog):
    with caplog.at_level(logging.ERROR, logger="fsm.platform.admin_alerts"):
        _send(RaisingEmailSender(), frozenset({"admin@example.com"}))

    assert any("admin@example.com" in r.getMessage() for r in caplog.records)
