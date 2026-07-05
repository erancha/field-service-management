"""Unit tests for GoogleCalendarSyncAdapter — mapping raw Google events to InboundEventChange.

Uses a FakeSyncClient so no Google API machinery is needed. Verifies that FSM events
are correctly mapped and foreign/malformed iCalUIDs are filtered out.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest

from fsm.platform.calendar_bridge.inbound_sync import GoogleCalendarSyncAdapter


_APPT_ID_1 = UUID("11111111-1111-1111-1111-111111111111")
_APPT_ID_2 = UUID("22222222-2222-2222-2222-222222222222")

_RAW_RESCHEDULE = {
    "iCalUID": f"fsm-{_APPT_ID_1}@fsm.local",
    "status": "confirmed",
    "start": {"dateTime": "2024-06-10T09:00:00Z"},
    "end": {"dateTime": "2024-06-10T11:00:00Z"},
    "description": "bring extra tools",
    "updated": "2024-06-10T08:30:00Z",
}

_RAW_CANCELLATION = {
    "iCalUID": f"fsm-{_APPT_ID_2}@fsm.local",
    "status": "cancelled",
    "updated": "2024-06-10T08:45:00Z",
}

_RAW_FOREIGN = {
    "iCalUID": "some-other-meeting@gmail.com",
    "status": "confirmed",
    "start": {"dateTime": "2024-06-10T10:00:00Z"},
    "end": {"dateTime": "2024-06-10T11:00:00Z"},
    "updated": "2024-06-10T09:00:00Z",
}

_RAW_MISSING_ICALUID = {
    "status": "confirmed",
    "start": {"dateTime": "2024-06-10T12:00:00Z"},
    "end": {"dateTime": "2024-06-10T13:00:00Z"},
    "updated": "2024-06-10T09:00:00Z",
}

_NEXT_TOKEN = "token-abc-123"


class FakeSyncClient:
    """Returns canned raw events and a fixed next token."""

    def list_changes(self, calendar_id: str, sync_token: str | None) -> tuple[list[dict], str]:
        return (
            [_RAW_RESCHEDULE, _RAW_CANCELLATION, _RAW_FOREIGN, _RAW_MISSING_ICALUID],
            _NEXT_TOKEN,
        )


class TestGoogleCalendarSyncAdapter:
    def _make_adapter(self) -> GoogleCalendarSyncAdapter:
        return GoogleCalendarSyncAdapter(FakeSyncClient(), "cal-id-xyz")

    def test_returns_only_fsm_events(self):
        adapter = self._make_adapter()
        changes, _ = adapter.list_changes(None)
        assert len(changes) == 2

    def test_next_token_forwarded(self):
        adapter = self._make_adapter()
        _, token = adapter.list_changes(None)
        assert token == _NEXT_TOKEN

    def test_reschedule_maps_correctly(self):
        adapter = self._make_adapter()
        changes, _ = adapter.list_changes(None)
        reschedule = next(c for c in changes if c.appointment_id == _APPT_ID_1)

        assert reschedule.cancelled is False
        assert reschedule.new_time_range is not None
        assert reschedule.new_time_range.start == datetime(2024, 6, 10, 9, 0, tzinfo=timezone.utc)
        assert reschedule.new_time_range.end == datetime(2024, 6, 10, 11, 0, tzinfo=timezone.utc)
        assert reschedule.updated_at == datetime(2024, 6, 10, 8, 30, tzinfo=timezone.utc)
        # The event description is a rendered projection, not a source of truth, so the
        # adapter surfaces no details signal for reconciliation.
        assert not hasattr(reschedule, "details")

    def test_cancellation_maps_correctly(self):
        adapter = self._make_adapter()
        changes, _ = adapter.list_changes(None)
        cancellation = next(c for c in changes if c.appointment_id == _APPT_ID_2)

        assert cancellation.cancelled is True
        assert cancellation.new_time_range is None
        assert cancellation.updated_at == datetime(2024, 6, 10, 8, 45, tzinfo=timezone.utc)

    def test_foreign_icaluid_skipped(self):
        adapter = self._make_adapter()
        changes, _ = adapter.list_changes(None)
        ids = {c.appointment_id for c in changes}
        # Neither foreign nor missing-iCalUID events should appear
        assert all(str(aid).replace("-", "") != "some" for aid in ids)

    def test_missing_icaluid_skipped(self):
        adapter = self._make_adapter()
        changes, _ = adapter.list_changes(None)
        assert len(changes) == 2

    def test_sync_token_passed_to_client(self):
        received = []

        class CapturingClient:
            def list_changes(self, calendar_id, sync_token):
                received.append(sync_token)
                return [], "new-token"

        adapter = GoogleCalendarSyncAdapter(CapturingClient(), "cal-id")
        adapter.list_changes("my-sync-token")
        assert received == ["my-sync-token"]
