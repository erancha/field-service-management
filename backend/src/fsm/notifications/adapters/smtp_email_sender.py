"""Email sender adapters: SMTP (real) and logging (fallback)."""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

_log = logging.getLogger(__name__)


class SmtpEmailSender:
    """EmailSender that delivers via SMTP using the stdlib smtplib.

    When `ics` is provided it is attached as text/calendar;method=REQUEST.
    TLS is used when use_tls is True (STARTTLS on the configured port).
    """

    def __init__(
        self,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
        from_addr: str,
        use_tls: bool = True,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._from_addr = from_addr
        self._use_tls = use_tls

    def send(
        self,
        to: str,
        subject: str,
        body: str,
        ics: str | None = None,
    ) -> None:
        msg = EmailMessage()
        msg["From"] = self._from_addr
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)

        if ics is not None:
            msg.add_attachment(
                ics.encode(),
                maintype="text",
                subtype="calendar",
                params={"method": "REQUEST"},
                filename="invite.ics",
            )

        with smtplib.SMTP(self._host, self._port) as smtp:
            if self._use_tls:
                smtp.starttls()
            if self._username and self._password:
                smtp.login(self._username, self._password)
            smtp.send_message(msg)


class LoggingEmailSender:
    """EmailSender that logs instead of sending — used when SMTP is unconfigured."""

    def send(
        self,
        to: str,
        subject: str,
        body: str,
        ics: str | None = None,
    ) -> None:
        _log.info(
            "Email (logging fallback) to=%s subject=%r ics_attached=%s",
            to,
            subject,
            ics is not None,
        )
