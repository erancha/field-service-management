"""Thin seam isolating the Google Calendar API fluent chain.

Defines a narrow GoogleCalendarClient protocol whose methods accept and return
plain Python types, so the adapter's mapping logic can be tested without any
googleapiclient machinery. GoogleApiCalendarClient wraps the discovery service
resource and is the only file that touches the fluent chain.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

_log = logging.getLogger(__name__)


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


class GoogleApiCalendarClient:
    """Wraps a googleapiclient discovery service resource.

    Translates the narrow GoogleCalendarClient calls into the fluent API chain
    expected by googleapiclient. Constructed with a discovery service object
    obtained from googleapiclient.discovery.build.
    """

    def __init__(self, service: Any) -> None:
        self._service = service

    def import_event(self, calendar_id: str, body: dict) -> dict:
        return self._service.events().import_(calendarId=calendar_id, body=body).execute()

    def update_event(self, calendar_id: str, event_id: str, body: dict) -> dict:
        return (
            self._service.events()
            .update(calendarId=calendar_id, eventId=event_id, body=body)
            .execute()
        )

    def delete_event(self, calendar_id: str, event_id: str) -> None:
        self._service.events().delete(calendarId=calendar_id, eventId=event_id).execute()

    def query_busy(
        self,
        calendar_id: str,
        time_min: datetime,
        time_max: datetime,
    ) -> list[tuple[datetime, datetime]]:
        body = {
            "timeMin": time_min.isoformat(),
            "timeMax": time_max.isoformat(),
            "items": [{"id": calendar_id}],
        }
        response = self._service.freebusy().query(body=body).execute()
        raw_intervals: list[dict] = response.get("calendars", {}).get(calendar_id, {}).get("busy", [])
        result: list[tuple[datetime, datetime]] = []
        for interval in raw_intervals:
            start = datetime.fromisoformat(interval["start"]).astimezone(timezone.utc)
            end = datetime.fromisoformat(interval["end"]).astimezone(timezone.utc)
            result.append((start, end))
        return result

    def create_calendar(self, summary: str) -> str:
        return self._service.calendars().insert(body={"summary": summary}).execute()["id"]

    def list_changes(
        self, calendar_id: str, sync_token: str | None
    ) -> tuple[list[dict], str]:
        """Retrieve all changed events since sync_token, paginating to completion.

        On HTTP 410 (expired/invalid sync token) performs a full resync without
        a token. Accumulates items from all pages; returns them with the final
        nextSyncToken.
        """
        def _fetch(*, with_sync_token: bool) -> tuple[list[dict], str]:
            base_params: dict[str, Any] = {
                "calendarId": calendar_id,
                "singleEvents": True,
                "showDeleted": True,
            }
            if with_sync_token and sync_token is not None:
                base_params["syncToken"] = sync_token

            items: list[dict] = []
            page_token: str | None = None

            while True:
                params = dict(base_params)
                if page_token is not None:
                    params["pageToken"] = page_token

                page = self._service.events().list(**params).execute()
                items.extend(page.get("items", []))

                page_token = page.get("nextPageToken")
                if page_token is None:
                    return items, page["nextSyncToken"]

        try:
            return _fetch(with_sync_token=True)
        except Exception as exc:
            # googleapiclient.HttpError exposes the HTTP status via resp.status;
            # use duck typing to avoid importing googleapiclient here, which would
            # create a transitive dependency from calendar.application.
            status = getattr(getattr(exc, "resp", None), "status", None)
            if status == 410:
                _log.warning(
                    "Sync token expired (410) for calendar %s; performing full resync",
                    calendar_id,
                )
                return _fetch(with_sync_token=False)
            raise
