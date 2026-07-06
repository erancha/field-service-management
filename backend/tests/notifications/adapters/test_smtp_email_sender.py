"""Unit tests for SmtpEmailSender message construction (no SMTP connection involved)."""
from __future__ import annotations

import ssl
from unittest.mock import MagicMock, patch

from fsm.notifications.adapters.smtp_email_sender import SmtpEmailSender


def _sender() -> SmtpEmailSender:
    return SmtpEmailSender(
        host="smtp.example.com",
        port=587,
        username=None,
        password=None,
        from_addr="ops@fsm.example",
    )


class TestMessageConstruction:
    def test_message_carries_recipient_subject_and_body(self):
        msg = _sender()._build_message("c@example.com", "Booked", "body")

        assert msg["To"] == "c@example.com"
        assert msg["From"] == "ops@fsm.example"
        assert msg["Subject"] == "Booked"
        assert msg.get_content().strip() == "body"

    def test_no_attachment_is_added(self):
        msg = _sender()._build_message("c@example.com", "Booked", "body")

        assert list(msg.iter_attachments()) == []


class TestStartTlsCertificateVerification:
    def test_starttls_verifies_the_server_certificate(self):
        smtp_instance = MagicMock()
        smtp_instance.__enter__.return_value = smtp_instance
        with patch("smtplib.SMTP", return_value=smtp_instance) as smtp_cls:
            _sender().send("c@example.com", "Booked", "body")

        (args, _kwargs) = smtp_cls.call_args
        assert args[:2] == ("smtp.example.com", 587)
        (_args, kwargs) = smtp_instance.starttls.call_args
        context = kwargs["context"]
        assert context.verify_mode == ssl.CERT_REQUIRED
        assert context.check_hostname is True


class TestConnectTimeout:
    def test_send_passes_a_finite_timeout_to_smtp_connect(self):
        smtp_instance = MagicMock()
        smtp_instance.__enter__.return_value = smtp_instance
        sender = SmtpEmailSender(
            host="smtp.example.com",
            port=587,
            username=None,
            password=None,
            from_addr="ops@fsm.example",
            timeout=7.5,
        )
        with patch("smtplib.SMTP", return_value=smtp_instance) as smtp_cls:
            sender.send("c@example.com", "Booked", "body")

        (_args, kwargs) = smtp_cls.call_args
        assert kwargs["timeout"] == 7.5

    def test_default_timeout_is_finite(self):
        smtp_instance = MagicMock()
        smtp_instance.__enter__.return_value = smtp_instance
        with patch("smtplib.SMTP", return_value=smtp_instance) as smtp_cls:
            _sender().send("c@example.com", "Booked", "body")

        (_args, kwargs) = smtp_cls.call_args
        assert kwargs["timeout"] is not None
        assert kwargs["timeout"] > 0
