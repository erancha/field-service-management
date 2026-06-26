"""Holiday reader for Google public holiday calendars.

Uses a service API key (not OAuth) to read all-day events from a public
holiday calendar. The reader paginates automatically and skips events that
lack a start.date field (timed events, cancelled placeholders).
"""
from __future__ import annotations

from datetime import date
from typing import Any, Protocol, runtime_checkable

import googleapiclient.discovery


@runtime_checkable
class HolidayReader(Protocol):
    """Narrow outbound interface for reading public holiday events."""

    def list_holidays(
        self,
        calendar_id: str,
        time_min: date,
        time_max: date,
    ) -> list[tuple[date, str]]:
        """Return (date, name) pairs for all-day events in [time_min, time_max)."""
        ...


class GoogleApiHolidayReader:
    """Wraps a googleapiclient calendar discovery resource.

    Reads all-day events from a public holiday calendar identified by calendar_id.
    Requires a developer API key (not per-user OAuth) — public holiday calendars
    are accessible to any authenticated API key.
    """

    def __init__(self, service: Any) -> None:
        self._service = service

    def list_holidays(
        self,
        calendar_id: str,
        time_min: date,
        time_max: date,
    ) -> list[tuple[date, str]]:
        """Return (date, name) pairs; paginates to completion.

        Skips events that lack start.date (timed events or malformed entries).
        """
        time_min_rfc = f"{time_min.isoformat()}T00:00:00Z"
        time_max_rfc = f"{time_max.isoformat()}T00:00:00Z"

        results: list[tuple[date, str]] = []
        page_token: str | None = None

        while True:
            params: dict[str, Any] = {
                "calendarId": calendar_id,
                "timeMin": time_min_rfc,
                "timeMax": time_max_rfc,
                "singleEvents": True,
                "orderBy": "startTime",
            }
            if page_token is not None:
                params["pageToken"] = page_token

            page = self._service.events().list(**params).execute()

            for event in page.get("items", []):
                start = event.get("start", {})
                if "date" not in start:
                    continue
                results.append(
                    (date.fromisoformat(start["date"]), event.get("summary", ""))
                )

            page_token = page.get("nextPageToken")
            if page_token is None:
                break

        return results


def build_holiday_reader(api_key: str) -> GoogleApiHolidayReader:
    """Build a GoogleApiHolidayReader using a developer API key.

    Public holiday calendars are readable with a developer key — no OAuth grant needed.
    cache_discovery=False avoids stale discovery docs in serverless / ephemeral environments.
    """
    service = googleapiclient.discovery.build(
        "calendar", "v3", developerKey=api_key, cache_discovery=False
    )
    return GoogleApiHolidayReader(service)
