"""Outbound port for a Google Calendar API backend.

The protocol's methods accept and return plain Python types, so the application layer and
the platform bridge can be exercised with fakes that never touch googleapiclient machinery.
"""
from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable


@runtime_checkable
class GoogleCalendarClient(Protocol):
    """Narrow outbound interface to a Google Calendar API backend."""

    def import_event(self, calendar_id: str, body: dict) -> dict:
        """Upsert an event by iCalUID and return the resource dict.

        Wraps events.import_, which creates the event if the iCalUID is new or
        updates the existing event if the iCalUID already exists. This makes
        CREATE idempotent: retrying with the same iCalUID resolves to the same
        Google Calendar event rather than creating a duplicate.
        """
        ...

    def update_event(self, calendar_id: str, event_id: str, body: dict) -> dict:
        """Replace an existing event resource and return the updated resource dict."""
        ...

    def delete_event(self, calendar_id: str, event_id: str) -> None:
        """Delete the event; no return value."""
        ...

    def query_busy(
        self,
        calendar_id: str,
        time_min: datetime,
        time_max: datetime,
    ) -> list[tuple[datetime, datetime]]:
        """Return busy intervals within [time_min, time_max) as aware datetime pairs."""
        ...

    def create_calendar(self, summary: str) -> str:
        """Create a new calendar with the given summary and return its id."""
        ...

    def list_changes(
        self, calendar_id: str, sync_token: str | None
    ) -> tuple[list[dict], str]:
        """Return all changed events since sync_token and the next sync token.

        When sync_token is None, performs a full listing. On an HTTP 410 (expired
        sync token), retries with a full listing to recover a fresh sync token.
        Paginates automatically; the returned list accumulates all pages.
        """
        ...
