"""Unit tests for SmtpEmailSender message construction (no SMTP connection involved)."""
from __future__ import annotations

from fsm.notifications.adapters.smtp_email_sender import SmtpEmailSender


def _sender() -> SmtpEmailSender:
    return SmtpEmailSender(
        host="smtp.example.com",
        port=587,
        username=None,
        password=None,
        from_addr="ops@fsm.example",
    )


def _calendar_part(msg):
    return next(p for p in msg.iter_attachments() if p.get_content_subtype() == "calendar")


class TestCalendarAttachmentMethod:
    def test_request_invitation_carries_method_request(self):
        ics = "BEGIN:VCALENDAR\r\nMETHOD:REQUEST\r\nBEGIN:VEVENT\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"

        msg = _sender()._build_message("c@example.com", "Booked", "body", ics)

        part = _calendar_part(msg)
        assert part.get_param("method") == "REQUEST"

    def test_cancel_invitation_carries_method_cancel(self):
        ics = "BEGIN:VCALENDAR\r\nMETHOD:CANCEL\r\nBEGIN:VEVENT\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"

        msg = _sender()._build_message("c@example.com", "Cancelled", "body", ics)

        part = _calendar_part(msg)
        assert part.get_param("method") == "CANCEL"

    def test_plain_event_without_method_property_gets_no_method_param(self):
        ics = "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"

        msg = _sender()._build_message("c@example.com", "Booked", "body", ics)

        part = _calendar_part(msg)
        assert part.get_param("method") is None

    def test_attachment_keeps_charset_and_filename(self):
        ics = "BEGIN:VCALENDAR\r\nMETHOD:REQUEST\r\nEND:VCALENDAR\r\n"

        msg = _sender()._build_message("c@example.com", "Booked", "body", ics)

        part = _calendar_part(msg)
        assert part.get_param("charset") == "utf-8"
        assert part.get_filename() == "invite.ics"


class TestMessageWithoutIcs:
    def test_no_attachment_is_added(self):
        msg = _sender()._build_message("c@example.com", "Booked", "body", None)

        assert list(msg.iter_attachments()) == []
        assert msg["To"] == "c@example.com"
        assert msg["From"] == "ops@fsm.example"
