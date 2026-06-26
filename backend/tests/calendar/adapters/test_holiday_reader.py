"""Unit tests for GoogleApiHolidayReader.

Uses a fake service that returns canned event pages without any network I/O.
"""
from __future__ import annotations

from datetime import date

from fsm.calendar.adapters.holiday_reader import GoogleApiHolidayReader


def _fake_service(pages: list[list[dict]]) -> object:
    """Build a minimal fake discovery service that pages through the given event lists."""
    page_iter = iter(pages)

    class _FakeExecute:
        def __init__(self, page):
            self._page = page

        def execute(self):
            return self._page

    class _FakeList:
        def __init__(self):
            self._page_index = 0

        def list(self, **_kwargs):
            try:
                return _FakeExecute(next(page_iter))
            except StopIteration:
                return _FakeExecute({"items": [], "nextSyncToken": "done"})

    class _FakeEvents:
        def events(self):
            return _FakeList()

    return _FakeEvents()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_maps_all_day_events_to_date_name_tuples():
    page = {
        "items": [
            {"summary": "New Year's Day", "start": {"date": "2025-01-01"}},
            {"summary": "Independence Day", "start": {"date": "2025-07-04"}},
        ]
    }
    service = _fake_service([page])
    reader = GoogleApiHolidayReader(service)

    result = reader.list_holidays("cal-id", date(2025, 1, 1), date(2025, 12, 31))

    assert (date(2025, 1, 1), "New Year's Day") in result
    assert (date(2025, 7, 4), "Independence Day") in result


def test_skips_events_without_start_date():
    page = {
        "items": [
            # Timed event — has dateTime, not date
            {"summary": "Timed event", "start": {"dateTime": "2025-03-15T10:00:00Z"}},
            # Malformed — no start at all
            {"summary": "No start"},
            # Valid all-day event
            {"summary": "Valid Holiday", "start": {"date": "2025-11-11"}},
        ]
    }
    service = _fake_service([page])
    reader = GoogleApiHolidayReader(service)

    result = reader.list_holidays("cal-id", date(2025, 1, 1), date(2025, 12, 31))

    assert result == [(date(2025, 11, 11), "Valid Holiday")]


def test_paginates_across_multiple_pages():
    page1 = {
        "items": [{"summary": "Holiday A", "start": {"date": "2025-02-01"}}],
        "nextPageToken": "tok1",
    }
    page2 = {
        "items": [{"summary": "Holiday B", "start": {"date": "2025-03-01"}}],
    }
    service = _fake_service([page1, page2])
    reader = GoogleApiHolidayReader(service)

    result = reader.list_holidays("cal-id", date(2025, 1, 1), date(2025, 12, 31))

    assert len(result) == 2
    assert (date(2025, 2, 1), "Holiday A") in result
    assert (date(2025, 3, 1), "Holiday B") in result


def test_empty_summary_defaults_to_empty_string():
    page = {
        "items": [
            {"start": {"date": "2025-05-05"}},  # no summary key
        ]
    }
    service = _fake_service([page])
    reader = GoogleApiHolidayReader(service)

    result = reader.list_holidays("cal-id", date(2025, 1, 1), date(2025, 12, 31))

    assert result == [(date(2025, 5, 5), "")]
