"""Unit tests for GoogleCalendarAdapter.

Uses a hand-written FakeGoogleCalendarClient so no network or googleapiclient
dependency is needed in these tests.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import pytest

from fsm.calendar.adapters.client import GoogleCalendarClient
from fsm.calendar.adapters.google_calendar import GoogleCalendarAdapter
from fsm.scheduling.domain.appointment import Appointment, AppointmentStatus
from fsm.scheduling.domain.appointment_context import AppointmentContext
from fsm.scheduling.domain.time_range import TimeRange


# ---------------------------------------------------------------------------
# Fake client
# ---------------------------------------------------------------------------

class FakeGoogleCalendarClient:
    """Hand-written test double implementing GoogleCalendarClient.

    Records all calls so tests can inspect them; returns canned responses.
    import_event upserts by iCalUID, matching the idempotency guarantee of the
    real events.import_ API.
    """

    def __init__(self, busy: list[tuple[datetime, datetime]] | None = None) -> None:
        self._busy = busy or []
        self._by_ical_uid: dict[str, str] = {}
        self.imported: list[tuple[str, dict]] = []
        self.updated: list[tuple[str, str, dict]] = []
        self.deleted: list[tuple[str, str]] = []

    def import_event(self, calendar_id: str, body: dict) -> dict:
        ical_uid = body.get("iCalUID", "")
        if ical_uid not in self._by_ical_uid:
            self._by_ical_uid[ical_uid] = "evt-123"
        self.imported.append((calendar_id, body))
        return {"id": self._by_ical_uid[ical_uid]}

    def update_event(self, calendar_id: str, event_id: str, body: dict) -> dict:
        self.updated.append((calendar_id, event_id, body))
        return {"id": event_id}

    def delete_event(self, calendar_id: str, event_id: str) -> None:
        self.deleted.append((calendar_id, event_id))

    def query_busy(
        self,
        calendar_id: str,
        time_min: datetime,
        time_max: datetime,
    ) -> list[tuple[datetime, datetime]]:
        return self._busy

    def create_calendar(self, summary: str) -> str:
        return "fake-calendar-id"

    def list_changes(
        self, calendar_id: str, sync_token: str | None
    ) -> tuple[list[dict], str]:
        return [], "fake-sync-token"


# Verify at runtime that the fake satisfies the protocol
assert isinstance(FakeGoogleCalendarClient(), GoogleCalendarClient)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CALENDAR_ID = "test-calendar@example.com"

START = datetime(2025, 6, 1, 9, 0, tzinfo=timezone.utc)
END = datetime(2025, 6, 1, 10, 0, tzinfo=timezone.utc)


@pytest.fixture()
def appointment() -> Appointment:
    now = datetime(2025, 6, 1, 8, 0, tzinfo=timezone.utc)
    return Appointment(
        id=uuid.uuid4(),
        service_call_id=uuid.uuid4(),
        technician_id=uuid.uuid4(),
        customer_id=uuid.uuid4(),
        time_range=TimeRange(start=START, end=END),
        status=AppointmentStatus.SCHEDULED,
        details="Check HVAC unit",
        created_at=now,
        updated_at=now,
    )


@pytest.fixture()
def appointment_no_details() -> Appointment:
    now = datetime(2025, 6, 1, 8, 0, tzinfo=timezone.utc)
    return Appointment(
        id=uuid.uuid4(),
        service_call_id=uuid.uuid4(),
        technician_id=uuid.uuid4(),
        customer_id=uuid.uuid4(),
        time_range=TimeRange(start=START, end=END),
        status=AppointmentStatus.SCHEDULED,
        details=None,
        created_at=now,
        updated_at=now,
    )


@pytest.fixture()
def context() -> AppointmentContext:
    return AppointmentContext(customer_name="Ada Lovelace", problem_description="No hot water")


# ---------------------------------------------------------------------------
# create_event
# ---------------------------------------------------------------------------

class TestCreateEvent:
    def test_returns_event_id_from_client(
        self, appointment: Appointment, context: AppointmentContext
    ) -> None:
        client = FakeGoogleCalendarClient()
        adapter = GoogleCalendarAdapter(client=client, calendar_id=CALENDAR_ID)

        event_id = adapter.create_event(appointment, context)

        assert event_id == "evt-123"

    def test_passes_calendar_id_to_client(self, appointment: Appointment) -> None:
        client = FakeGoogleCalendarClient()
        adapter = GoogleCalendarAdapter(client=client, calendar_id=CALENDAR_ID)

        adapter.create_event(appointment)

        cal_id, _ = client.imported[0]
        assert cal_id == CALENDAR_ID

    def test_body_has_ical_uid(self, appointment: Appointment) -> None:
        """create_event sets iCalUID so retried calls upsert rather than duplicate."""
        client = FakeGoogleCalendarClient()
        adapter = GoogleCalendarAdapter(client=client, calendar_id=CALENDAR_ID)

        adapter.create_event(appointment)

        _, body = client.imported[0]
        assert body["iCalUID"] == f"fsm-{appointment.id}@fsm.local"

    def test_body_has_summary(self, appointment: Appointment) -> None:
        client = FakeGoogleCalendarClient()
        adapter = GoogleCalendarAdapter(client=client, calendar_id=CALENDAR_ID)

        adapter.create_event(appointment)

        _, body = client.imported[0]
        assert body["summary"] == "Field service appointment"

    def test_body_has_rfc3339_start(self, appointment: Appointment) -> None:
        client = FakeGoogleCalendarClient()
        adapter = GoogleCalendarAdapter(client=client, calendar_id=CALENDAR_ID)

        adapter.create_event(appointment)

        _, body = client.imported[0]
        assert body["start"]["dateTime"] == START.isoformat()

    def test_body_has_rfc3339_end(self, appointment: Appointment) -> None:
        client = FakeGoogleCalendarClient()
        adapter = GoogleCalendarAdapter(client=client, calendar_id=CALENDAR_ID)

        adapter.create_event(appointment)

        _, body = client.imported[0]
        assert body["end"]["dateTime"] == END.isoformat()

    def test_body_includes_description_when_details_present(
        self, appointment: Appointment
    ) -> None:
        client = FakeGoogleCalendarClient()
        adapter = GoogleCalendarAdapter(client=client, calendar_id=CALENDAR_ID)

        adapter.create_event(appointment)

        _, body = client.imported[0]
        assert body["description"] == "Check HVAC unit"

    def test_body_omits_description_when_details_absent(
        self, appointment_no_details: Appointment
    ) -> None:
        client = FakeGoogleCalendarClient()
        adapter = GoogleCalendarAdapter(client=client, calendar_id=CALENDAR_ID)

        adapter.create_event(appointment_no_details)

        _, body = client.imported[0]
        assert "description" not in body

    def test_retried_create_returns_same_event_id(self, appointment: Appointment) -> None:
        """A second create_event call with the same appointment returns the same event id."""
        client = FakeGoogleCalendarClient()
        adapter = GoogleCalendarAdapter(client=client, calendar_id=CALENDAR_ID)

        id1 = adapter.create_event(appointment)
        id2 = adapter.create_event(appointment)

        assert id1 == id2, "Idempotent import_event must return the same id on retry"


# ---------------------------------------------------------------------------
# update_event
# ---------------------------------------------------------------------------

class TestUpdateEvent:
    def test_passes_event_id_to_client(self, appointment: Appointment) -> None:
        client = FakeGoogleCalendarClient()
        adapter = GoogleCalendarAdapter(client=client, calendar_id=CALENDAR_ID)

        adapter.update_event("evt-456", appointment)

        cal_id, event_id, _ = client.updated[0]
        assert cal_id == CALENDAR_ID
        assert event_id == "evt-456"

    def test_body_matches_appointment(self, appointment: Appointment) -> None:
        client = FakeGoogleCalendarClient()
        adapter = GoogleCalendarAdapter(client=client, calendar_id=CALENDAR_ID)

        adapter.update_event("evt-456", appointment)

        _, _, body = client.updated[0]
        assert body["summary"] == "Field service appointment"
        assert body["start"]["dateTime"] == START.isoformat()
        assert body["end"]["dateTime"] == END.isoformat()
        assert body["description"] == "Check HVAC unit"


# ---------------------------------------------------------------------------
# delete_event
# ---------------------------------------------------------------------------

class TestDeleteEvent:
    def test_passes_calendar_and_event_id_to_client(self, appointment: Appointment) -> None:
        client = FakeGoogleCalendarClient()
        adapter = GoogleCalendarAdapter(client=client, calendar_id=CALENDAR_ID)

        adapter.delete_event("evt-789")

        assert client.deleted == [(CALENDAR_ID, "evt-789")]


# ---------------------------------------------------------------------------
# get_busy
# ---------------------------------------------------------------------------

class TestGetBusy:
    def test_maps_tuples_to_time_ranges(self) -> None:
        busy_start = datetime(2025, 6, 1, 9, 0, tzinfo=timezone.utc)
        busy_end = datetime(2025, 6, 1, 9, 30, tzinfo=timezone.utc)
        client = FakeGoogleCalendarClient(busy=[(busy_start, busy_end)])
        adapter = GoogleCalendarAdapter(client=client, calendar_id=CALENDAR_ID)

        result = adapter.get_busy(
            technician_id=uuid.uuid4(),
            start=START,
            end=END,
        )

        assert len(result) == 1
        assert result[0] == TimeRange(start=busy_start, end=busy_end)

    def test_returns_empty_list_when_no_busy(self) -> None:
        client = FakeGoogleCalendarClient(busy=[])
        adapter = GoogleCalendarAdapter(client=client, calendar_id=CALENDAR_ID)

        result = adapter.get_busy(
            technician_id=uuid.uuid4(),
            start=START,
            end=END,
        )

        assert result == []

    def test_preserves_multiple_busy_intervals(self) -> None:
        intervals = [
            (datetime(2025, 6, 1, 9, 0, tzinfo=timezone.utc),
             datetime(2025, 6, 1, 9, 30, tzinfo=timezone.utc)),
            (datetime(2025, 6, 1, 9, 45, tzinfo=timezone.utc),
             datetime(2025, 6, 1, 10, 0, tzinfo=timezone.utc)),
        ]
        client = FakeGoogleCalendarClient(busy=intervals)
        adapter = GoogleCalendarAdapter(client=client, calendar_id=CALENDAR_ID)

        result = adapter.get_busy(
            technician_id=uuid.uuid4(),
            start=START,
            end=END,
        )

        assert len(result) == 2
        assert result[0] == TimeRange(*intervals[0])
        assert result[1] == TimeRange(*intervals[1])


# ---------------------------------------------------------------------------
# _build_body / context rendering
# ---------------------------------------------------------------------------

class TestBuildBody:
    def test_title_combines_customer_and_problem(
        self, appointment: Appointment, context: AppointmentContext
    ) -> None:
        client = FakeGoogleCalendarClient()
        adapter = GoogleCalendarAdapter(client=client, calendar_id=CALENDAR_ID)

        adapter.create_event(appointment, context)

        body = client.imported[0][1]
        assert body["summary"] == "Ada Lovelace — No hot water"

    def test_description_combines_problem_and_details(
        self, appointment: Appointment, context: AppointmentContext
    ) -> None:
        client = FakeGoogleCalendarClient()
        adapter = GoogleCalendarAdapter(client=client, calendar_id=CALENDAR_ID)

        adapter.create_event(appointment, context)

        body = client.imported[0][1]
        assert body["description"] == "No hot water\n\nCheck HVAC unit"

    def test_description_is_problem_only_when_no_details(
        self, appointment_no_details: Appointment, context: AppointmentContext
    ) -> None:
        client = FakeGoogleCalendarClient()
        adapter = GoogleCalendarAdapter(client=client, calendar_id=CALENDAR_ID)

        adapter.create_event(appointment_no_details, context)

        body = client.imported[0][1]
        assert body["description"] == "No hot water"

    def test_title_falls_back_when_context_empty(
        self, appointment_no_details: Appointment
    ) -> None:
        client = FakeGoogleCalendarClient()
        adapter = GoogleCalendarAdapter(client=client, calendar_id=CALENDAR_ID)

        adapter.create_event(appointment_no_details, AppointmentContext())

        body = client.imported[0][1]
        assert body["summary"] == "Field service appointment"
        assert "description" not in body

    def test_long_problem_is_truncated_in_title(self, appointment_no_details: Appointment) -> None:
        client = FakeGoogleCalendarClient()
        adapter = GoogleCalendarAdapter(client=client, calendar_id=CALENDAR_ID)
        long_problem = "x" * 80
        ctx = AppointmentContext(customer_name="Ada", problem_description=long_problem)

        adapter.create_event(appointment_no_details, ctx)

        body = client.imported[0][1]
        assert body["summary"] == f"Ada — {'x' * 59}…"
