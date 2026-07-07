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

    def insert_event(self, calendar_id: str, body: dict, *, send_updates: str = "all") -> dict:
        """Create a new event and notify attendees per send_updates.

        Unlike events.import, this delivers guest invitations. A duplicate iCalUID raises the
        Google 409; callers recover the existing id via find_event_id_by_ical_uid.
        """
        ...

    def find_event_id_by_ical_uid(self, calendar_id: str, ical_uid: str) -> str | None:
        """Return the event id whose iCalUID matches, or None if not found."""
        ...

    def update_event(
        self, calendar_id: str, event_id: str, body: dict, *, send_updates: str = "all"
    ) -> dict:
        """Replace an existing event resource and return the updated resource dict."""
        ...

    def delete_event(self, calendar_id: str, event_id: str, *, send_updates: str = "all") -> None:
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

    def calendar_exists(self, calendar_id: str) -> bool:
        """Return whether a calendar with the given id still resolves on the account.

        False once the technician deletes the app-created calendar in Google; used to decide
        whether a reconnect can reuse the stored calendar or must provision a replacement. Google
        propagates a deletion with a short lag, so a just-deleted calendar can still report True
        briefly — recovery then lands on the next reconnect.
        """
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
