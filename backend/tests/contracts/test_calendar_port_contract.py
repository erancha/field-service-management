"""Behavioral contract tests for CalendarPort implementations (§11).

§11 of the FSM slice roadmap requires that the fake and the real adapter are verified
against the same behavioral contract so fakes stay faithful to real adapters. Any
divergence caught here indicates the fake must be updated — never the real adapter.

Both FakeCalendarPort and GoogleCalendarAdapter (backed by FakeGoogleCalendarClient) are
exercised against every assertion. A failure on one implementation but not the other means
the two have drifted apart.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Union

import pytest

from fsm.platform.calendar_bridge.google_calendar import GoogleCalendarAdapter
from fsm.scheduling.domain.appointment import Appointment, AppointmentStatus
from fsm.scheduling.domain.appointment_context import AppointmentContext
from fsm.scheduling.domain.time_range import TimeRange
from tests.scheduling.fakes import FakeCalendarPort, FakeGoogleCalendarClient

# ---------------------------------------------------------------------------
# Type alias for the union that the fixture can return
# ---------------------------------------------------------------------------

CalendarPortImpl = Union[FakeCalendarPort, GoogleCalendarAdapter]

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

_START = datetime(2025, 6, 1, 9, 0, tzinfo=timezone.utc)
_END = datetime(2025, 6, 1, 10, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Parametrized fixture — one fresh instance per implementation per test
# ---------------------------------------------------------------------------

def _make_fake() -> FakeCalendarPort:
    return FakeCalendarPort()


def _make_google_adapter() -> GoogleCalendarAdapter:
    return GoogleCalendarAdapter(FakeGoogleCalendarClient(), calendar_id="fsm-cal-test")


@pytest.fixture(params=["fake", "google_adapter"])
def calendar(request: pytest.FixtureRequest) -> CalendarPortImpl:
    """Yield a freshly constructed CalendarPort for each implementation under test."""
    if request.param == "fake":
        return _make_fake()
    return _make_google_adapter()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_appointment(appointment_id: uuid.UUID | None = None) -> Appointment:
    """Build a minimal tz-aware Appointment suitable for all port methods."""
    now = datetime(2025, 6, 1, 8, 0, tzinfo=timezone.utc)
    return Appointment(
        id=appointment_id or uuid.uuid4(),
        service_call_id=uuid.uuid4(),
        technician_id=uuid.uuid4(),
        customer_id=uuid.uuid4(),
        time_range=TimeRange(start=_START, end=_END),
        status=AppointmentStatus.SCHEDULED,
        details="HVAC inspection",
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# Contract: create_event
# ---------------------------------------------------------------------------

class TestCreateEvent:
    def test_returns_non_empty_string_id(self, calendar: CalendarPortImpl) -> None:
        appointment = _make_appointment()

        event_id = calendar.create_event(appointment, AppointmentContext())

        assert isinstance(event_id, str)
        assert len(event_id) > 0

    def test_idempotent_on_same_appointment(self, calendar: CalendarPortImpl) -> None:
        """Two create_event calls for the same appointment resolve to the same event id.

        This mirrors the dispatcher's retry safety: if a CREATE outbox entry is retried
        after a partial failure, both calls must return the same external id so no
        duplicate calendar events are created.
        """
        appointment = _make_appointment(appointment_id=uuid.UUID("12345678-1234-5678-1234-567812345678"))

        id1 = calendar.create_event(appointment, AppointmentContext())
        id2 = calendar.create_event(appointment, AppointmentContext())

        assert id1 == id2, (
            "create_event must be idempotent: repeated calls for the same appointment "
            "must return the same event id (upsert-by-iCalUID semantics)"
        )


# ---------------------------------------------------------------------------
# Contract: update_event
# ---------------------------------------------------------------------------

class TestUpdateEvent:
    def test_does_not_raise_for_existing_event(self, calendar: CalendarPortImpl) -> None:
        appointment = _make_appointment()
        event_id = calendar.create_event(appointment, AppointmentContext())

        # A second appointment representing the rescheduled version.
        updated = _make_appointment(appointment_id=appointment.id)

        # Must not raise.
        calendar.update_event(event_id, updated, AppointmentContext())


# ---------------------------------------------------------------------------
# Contract: delete_event
# ---------------------------------------------------------------------------

class TestDeleteEvent:
    def test_does_not_raise_for_existing_event(self, calendar: CalendarPortImpl) -> None:
        appointment = _make_appointment()
        event_id = calendar.create_event(appointment, AppointmentContext())

        # Must not raise.
        calendar.delete_event(event_id)

    def test_does_not_raise_for_unknown_event_id(self, calendar: CalendarPortImpl) -> None:
        """Deleting an event that does not exist must be tolerated without raising.

        Both implementations treat delete as fire-and-forget: the fake appends to a list
        unconditionally; the Google adapter's client uses dict.pop with a default.
        """
        calendar.delete_event("nonexistent-event-id-xyz")


# ---------------------------------------------------------------------------
# Contract: get_busy
# ---------------------------------------------------------------------------

class TestGetBusy:
    def test_returns_list(self, calendar: CalendarPortImpl) -> None:
        technician_id = uuid.uuid4()

        result = calendar.get_busy(technician_id, _START, _END)

        assert isinstance(result, list)

    def test_returns_empty_list_when_no_busy_intervals(
        self, calendar: CalendarPortImpl
    ) -> None:
        """A technician with no known busy intervals produces an empty list."""
        technician_id = uuid.uuid4()

        result = calendar.get_busy(technician_id, _START, _END)

        assert result == []

    def test_every_element_is_time_range_with_start_before_end(
        self, calendar: CalendarPortImpl
    ) -> None:
        """Each returned interval is a well-formed TimeRange (start strictly < end).

        TimeRange.__post_init__ already enforces this invariant on construction, so a
        non-empty result list that passed construction is guaranteed to satisfy it.
        This test exercises the contract explicitly for documentation purposes.
        """
        technician_id = uuid.uuid4()

        # Seed a busy range when the implementation is the fake (the adapter derives
        # busy ranges from the underlying client, which returns [] by default and is
        # not wired to calendar events in the fake client).
        if isinstance(calendar, FakeCalendarPort):
            busy = TimeRange(
                start=datetime(2025, 6, 1, 9, 0, tzinfo=timezone.utc),
                end=datetime(2025, 6, 1, 9, 30, tzinfo=timezone.utc),
            )
            calendar.set_busy(technician_id, [busy])

        result = calendar.get_busy(technician_id, _START, _END)

        for interval in result:
            assert isinstance(interval, TimeRange)
            assert interval.start < interval.end
