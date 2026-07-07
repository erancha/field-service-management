"""Shared fakes for the notifications context's EmailSender port."""
from __future__ import annotations


class FakeEmailSender:
    """In-memory EmailSender that records calls."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    def send(self, to: str, subject: str, body: str) -> None:
        self.sent.append({"to": to, "subject": subject, "body": body})


class RaisingEmailSender:
    """EmailSender that always raises — used to verify the triggering flow is never broken."""

    def send(self, to: str, subject: str, body: str) -> None:
        raise RuntimeError("SMTP unavailable")
