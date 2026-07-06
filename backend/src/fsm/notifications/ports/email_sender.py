"""Port for sending outbound email."""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmailSender(Protocol):
    """Outbound port for sending an email."""

    def send(self, to: str, subject: str, body: str) -> None:
        """Send an email to `to`."""
        ...
