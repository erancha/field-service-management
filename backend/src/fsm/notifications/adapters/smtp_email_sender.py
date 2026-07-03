"""Email sender adapters: SMTP (real) and logging (fallback)."""
from __future__ import annotations

import logging
import re
import smtplib
from email.message import EmailMessage

_log = logging.getLogger(__name__)

# iTIP method declared by the invitation itself (RFC 5545 METHOD property).
_ICS_METHOD_RE = re.compile(r"^METHOD:([A-Za-z-]+)\r?$", re.MULTILINE)


def _ics_method(ics: str) -> str | None:
    """Return the METHOD the ICS payload declares, or None for a plain (non-iTIP) event.

    RFC 6047 requires the text/calendar Content-Type `method` parameter to match the payload's
    METHOD property — mail clients key iTIP processing (e.g. removing a cancelled event) on the
    parameter. Reading it from the payload makes disagreement impossible.
    """
    match = _ICS_METHOD_RE.search(ics)
    return match.group(1) if match else None


class SmtpEmailSender:
    """EmailSender that delivers via SMTP using the stdlib smtplib.

    When `ics` is provided it is attached as text/calendar with charset=utf-8, carrying the
    payload's own iTIP METHOD as the Content-Type method parameter (absent for plain events).
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
        msg = self._build_message(to, subject, body, ics)
        with smtplib.SMTP(self._host, self._port) as smtp:
            if self._use_tls:
                smtp.starttls()
            if self._username and self._password:
                smtp.login(self._username, self._password)
            smtp.send_message(msg)

    def _build_message(
        self,
        to: str,
        subject: str,
        body: str,
        ics: str | None,
    ) -> EmailMessage:
        msg = EmailMessage()
        msg["From"] = self._from_addr
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)

        if ics is not None:
            params = {"charset": "utf-8"}
            method = _ics_method(ics)
            if method is not None:
                params["method"] = method
            msg.add_attachment(
                ics.encode(),
                maintype="text",
                subtype="calendar",
                params=params,
                filename="invite.ics",
            )
        return msg


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
