"""Email sender adapters: SMTP (real) and logging (fallback)."""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage

_log = logging.getLogger(__name__)

# Socket timeout in seconds applied to every SMTP connection: it bounds connect and all subsequent
# operations, so a notification send can never park the calling request thread indefinitely.
_DEFAULT_SMTP_TIMEOUT = 10.0


class SmtpEmailSender:
    """EmailSender that delivers via SMTP using the stdlib smtplib.

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
        timeout: float = _DEFAULT_SMTP_TIMEOUT,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._from_addr = from_addr
        self._use_tls = use_tls
        self._timeout = timeout

    def send(self, to: str, subject: str, body: str) -> None:
        msg = self._build_message(to, subject, body)
        with smtplib.SMTP(self._host, self._port, timeout=self._timeout) as smtp:
            if self._use_tls:
                smtp.starttls(context=ssl.create_default_context())
            if self._username and self._password:
                smtp.login(self._username, self._password)
            smtp.send_message(msg)

    def _build_message(self, to: str, subject: str, body: str) -> EmailMessage:
        msg = EmailMessage()
        msg["From"] = self._from_addr
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        return msg


class LoggingEmailSender:
    """EmailSender that logs instead of sending — used when SMTP is unconfigured."""

    def send(self, to: str, subject: str, body: str) -> None:
        _log.info("Email (logging fallback) to=%s subject=%r", to, subject)
