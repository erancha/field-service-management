"""Port for sending outbound email."""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmailSender(Protocol):
    """Outbound port for sending an email, optionally with a calendar attachment."""

    def send(
        self,
        to: str,
        subject: str,
        body: str,
        ics: str | None = None,
    ) -> None:
        """Send an email to `to`. When `ics` is provided, attach it as text/calendar."""
        ...
