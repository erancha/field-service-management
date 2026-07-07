"""Unit tests for GoogleCalendarAdapter.

Uses a hand-written FakeGoogleCalendarClient so no network or googleapiclient
dependency is needed in these tests.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from fsm.google_calendar.ports.client import GoogleCalendarClient
from fsm.platform.calendar_bridge.google_calendar import GoogleCalendarAdapter
from fsm.scheduling.domain.appointment import Appointment, AppointmentStatus
from fsm.scheduling.domain.appointment_context import AppointmentContext
from fsm.scheduling.domain.time_range import TimeRange


# ---------------------------------------------------------------------------
# Fake client
# ---------------------------------------------------------------------------

class _FakeHttp409(Exception):
    """Duck-types googleapiclient.errors.HttpError's resp.status for a 409 duplicate."""

    def __init__(self) -> None:
        self.resp = type("R", (), {"status": 409})()


class FakeGoogleCalendarClient:
    """Hand-written test double implementing GoogleCalendarClient.

    Records all calls so tests can inspect them; returns canned responses.
    insert_event raises _FakeHttp409 on a duplicate iCalUID, matching the real
    events.insert behavior; find_event_id_by_ical_uid recovers the existing id.
    """

    def __init__(self, busy: list[tuple[datetime, datetime]] | None = None) -> None:
        self._busy = busy or []
        self._by_ical_uid: dict[str, str] = {}
        self.inserted: list[tuple[str, dict, str]] = []
        self.updated: list[tuple[str, str, dict, str]] = []
        self.deleted: list[tuple[str, str, str]] = []

    def insert_event(self, calendar_id: str, body: dict, *, send_updates: str = "all") -> dict:
        ical_uid = body.get("iCalUID", "")
        self.inserted.append((calendar_id, body, send_updates))
        if ical_uid in self._by_ical_uid:
            raise _FakeHttp409()
        self._by_ical_uid[ical_uid] = "evt-123"
        return {"id": self._by_ical_uid[ical_uid]}

    def find_event_id_by_ical_uid(self, calendar_id: str, ical_uid: str) -> str | None:
        return self._by_ical_uid.get(ical_uid)

    def update_event(
        self, calendar_id: str, event_id: str, body: dict, *, send_updates: str = "all"
    ) -> dict:
        self.updated.append((calendar_id, event_id, body, send_updates))
        return {"id": event_id}

    def delete_event(self, calendar_id: str, event_id: str, *, send_updates: str = "all") -> None:
        self.deleted.append((calendar_id, event_id, send_updates))

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

        adapter.create_event(appointment, AppointmentContext())

        cal_id, _, _ = client.inserted[0]
        assert cal_id == CALENDAR_ID

    def test_body_has_ical_uid(self, appointment: Appointment) -> None:
        """create_event sets iCalUID so retried calls upsert rather than duplicate."""
        client = FakeGoogleCalendarClient()
        adapter = GoogleCalendarAdapter(client=client, calendar_id=CALENDAR_ID)

        adapter.create_event(appointment, AppointmentContext())

        _, body, _ = client.inserted[0]
        assert body["iCalUID"] == f"fsm-{appointment.id}@fsm.local"

    def test_body_has_summary(self, appointment: Appointment) -> None:
        client = FakeGoogleCalendarClient()
        adapter = GoogleCalendarAdapter(client=client, calendar_id=CALENDAR_ID)

        adapter.create_event(appointment, AppointmentContext())

        _, body, _ = client.inserted[0]
        assert body["summary"] == "Field service appointment"

    def test_body_has_rfc3339_start(self, appointment: Appointment) -> None:
        client = FakeGoogleCalendarClient()
        adapter = GoogleCalendarAdapter(client=client, calendar_id=CALENDAR_ID)

        adapter.create_event(appointment, AppointmentContext())

        _, body, _ = client.inserted[0]
        assert body["start"]["dateTime"] == START.isoformat()

    def test_body_has_rfc3339_end(self, appointment: Appointment) -> None:
        client = FakeGoogleCalendarClient()
        adapter = GoogleCalendarAdapter(client=client, calendar_id=CALENDAR_ID)

        adapter.create_event(appointment, AppointmentContext())

        _, body, _ = client.inserted[0]
        assert body["end"]["dateTime"] == END.isoformat()

    def test_body_includes_description_when_details_present(
        self, appointment: Appointment
    ) -> None:
        client = FakeGoogleCalendarClient()
        adapter = GoogleCalendarAdapter(client=client, calendar_id=CALENDAR_ID)

        adapter.create_event(appointment, AppointmentContext())

        _, body, _ = client.inserted[0]
        assert body["description"] == "Check HVAC unit"

    def test_body_omits_description_when_details_absent(
        self, appointment_no_details: Appointment
    ) -> None:
        client = FakeGoogleCalendarClient()
        adapter = GoogleCalendarAdapter(client=client, calendar_id=CALENDAR_ID)

        adapter.create_event(appointment_no_details, AppointmentContext())

        _, body, _ = client.inserted[0]
        assert "description" not in body

    def test_retried_create_returns_same_event_id(self, appointment: Appointment) -> None:
        """A second create_event call with the same appointment returns the same event id."""
        client = FakeGoogleCalendarClient()
        adapter = GoogleCalendarAdapter(client=client, calendar_id=CALENDAR_ID)

        id1 = adapter.create_event(appointment, AppointmentContext())
        id2 = adapter.create_event(appointment, AppointmentContext())

        assert id1 == id2, "Idempotent insert_event (409-recovery) must return the same id on retry"


# ---------------------------------------------------------------------------
# Event timezone stamping
# ---------------------------------------------------------------------------

class TestEventTimezone:
    def test_boundaries_carry_injected_timezone(self, appointment: Appointment) -> None:
        client = FakeGoogleCalendarClient()
        adapter = GoogleCalendarAdapter(
            client=client, calendar_id=CALENDAR_ID, time_zone="Europe/Jerusalem"
        )

        adapter.create_event(appointment, AppointmentContext())

        _, body, _ = client.inserted[0]
        assert body["start"]["timeZone"] == "Europe/Jerusalem"
        assert body["end"]["timeZone"] == "Europe/Jerusalem"

    def test_boundaries_default_to_utc_when_no_zone_injected(
        self, appointment: Appointment
    ) -> None:
        client = FakeGoogleCalendarClient()
        adapter = GoogleCalendarAdapter(client=client, calendar_id=CALENDAR_ID)

        adapter.create_event(appointment, AppointmentContext())

        _, body, _ = client.inserted[0]
        assert body["start"]["timeZone"] == "UTC"
        assert body["end"]["timeZone"] == "UTC"


# ---------------------------------------------------------------------------
# update_event
# ---------------------------------------------------------------------------

class TestUpdateEvent:
    def test_passes_event_id_to_client(self, appointment: Appointment) -> None:
        client = FakeGoogleCalendarClient()
        adapter = GoogleCalendarAdapter(client=client, calendar_id=CALENDAR_ID)

        adapter.update_event("evt-456", appointment, AppointmentContext())

        cal_id, event_id, _, send_updates = client.updated[0]
        assert cal_id == CALENDAR_ID
        assert event_id == "evt-456"
        assert send_updates == "all"

    def test_body_matches_appointment(self, appointment: Appointment) -> None:
        client = FakeGoogleCalendarClient()
        adapter = GoogleCalendarAdapter(client=client, calendar_id=CALENDAR_ID)

        adapter.update_event("evt-456", appointment, AppointmentContext())

        _, _, body, _ = client.updated[0]
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

        assert client.deleted == [(CALENDAR_ID, "evt-789", "all")]


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

        body = client.inserted[0][1]
        assert body["summary"] == "Field Service Management: Ada Lovelace : No hot water"

    def test_description_combines_problem_and_details(
        self, appointment: Appointment, context: AppointmentContext
    ) -> None:
        client = FakeGoogleCalendarClient()
        adapter = GoogleCalendarAdapter(client=client, calendar_id=CALENDAR_ID)

        adapter.create_event(appointment, context)

        body = client.inserted[0][1]
        assert body["description"] == "No hot water\n\nCheck HVAC unit"

    def test_description_is_problem_only_when_no_details(
        self, appointment_no_details: Appointment, context: AppointmentContext
    ) -> None:
        client = FakeGoogleCalendarClient()
        adapter = GoogleCalendarAdapter(client=client, calendar_id=CALENDAR_ID)

        adapter.create_event(appointment_no_details, context)

        body = client.inserted[0][1]
        assert body["description"] == "No hot water"

    def test_title_falls_back_when_context_empty(
        self, appointment_no_details: Appointment
    ) -> None:
        client = FakeGoogleCalendarClient()
        adapter = GoogleCalendarAdapter(client=client, calendar_id=CALENDAR_ID)

        adapter.create_event(appointment_no_details, AppointmentContext())

        body = client.inserted[0][1]
        assert body["summary"] == "Field service appointment"
        assert "description" not in body

    def test_long_problem_is_truncated_in_title(self, appointment_no_details: Appointment) -> None:
        client = FakeGoogleCalendarClient()
        adapter = GoogleCalendarAdapter(client=client, calendar_id=CALENDAR_ID)
        long_problem = "x" * 80
        ctx = AppointmentContext(customer_name="Ada", problem_description=long_problem)

        adapter.create_event(appointment_no_details, ctx)

        body = client.inserted[0][1]
        assert body["summary"] == f"Field Service Management: Ada : {'x' * 59}…"

    def test_whitespace_only_problem_excluded_from_title_and_description(
        self, appointment_no_details: Appointment
    ) -> None:
        client = FakeGoogleCalendarClient()
        adapter = GoogleCalendarAdapter(client=client, calendar_id=CALENDAR_ID)

        adapter.create_event(
            appointment_no_details,
            AppointmentContext(customer_name="Ada", problem_description="   "),
        )

        body = client.inserted[0][1]
        assert body["summary"] == "Field Service Management: Ada"
        assert "description" not in body


class TestLocationAndPhone:
    def test_location_set_from_service_address(self, appointment: Appointment) -> None:
        client = FakeGoogleCalendarClient()
        adapter = GoogleCalendarAdapter(client=client, calendar_id=CALENDAR_ID)

        adapter.create_event(appointment, AppointmentContext(service_address="12 Main St"))

        body = client.inserted[0][1]
        assert body["location"] == "12 Main St"

    def test_location_omitted_when_address_absent_or_blank(
        self, appointment: Appointment
    ) -> None:
        client = FakeGoogleCalendarClient()
        adapter = GoogleCalendarAdapter(client=client, calendar_id=CALENDAR_ID)

        adapter.create_event(appointment, AppointmentContext(service_address="   "))

        body = client.inserted[0][1]
        assert "location" not in body

    def test_phone_appended_to_description(
        self, appointment_no_details: Appointment
    ) -> None:
        client = FakeGoogleCalendarClient()
        adapter = GoogleCalendarAdapter(client=client, calendar_id=CALENDAR_ID)
        context = AppointmentContext(
            problem_description="No hot water", customer_phone="+972-50-123"
        )

        adapter.create_event(appointment_no_details, context)

        body = client.inserted[0][1]
        assert body["description"] == "No hot water\n\nPhone: +972-50-123"

    def test_phone_alone_still_produces_description(
        self, appointment_no_details: Appointment
    ) -> None:
        client = FakeGoogleCalendarClient()
        adapter = GoogleCalendarAdapter(client=client, calendar_id=CALENDAR_ID)

        adapter.create_event(
            appointment_no_details, AppointmentContext(customer_phone="+972-50-123")
        )

        body = client.inserted[0][1]
        assert body["description"] == "Phone: +972-50-123"

    def test_technician_name_and_phone_lead_the_description(
        self, appointment_no_details: Appointment
    ) -> None:
        """The technician's own event echoes the contact the customer was given so the technician
        can confirm it is correct."""
        client = FakeGoogleCalendarClient()
        adapter = GoogleCalendarAdapter(client=client, calendar_id=CALENDAR_ID)
        context = AppointmentContext(
            problem_description="No hot water",
            customer_phone="+972-50-123",
            technician_name="Grace Hopper",
            technician_phone="+972-50-999",
        )

        adapter.create_event(appointment_no_details, context)

        body = client.inserted[0][1]
        assert body["description"] == (
            "Technician: Grace Hopper\nTechnician phone: +972-50-999"
            "\n\nNo hot water\n\nPhone: +972-50-123"
        )


# ---------------------------------------------------------------------------
# Customer attendee
# ---------------------------------------------------------------------------

def _appointment():
    now = datetime(2026, 7, 6, 9, 0, tzinfo=timezone.utc)
    return Appointment(
        id=uuid.uuid4(),
        service_call_id=uuid.uuid4(),
        technician_id=uuid.uuid4(),
        customer_id=uuid.uuid4(),
        time_range=TimeRange(now, datetime(2026, 7, 6, 10, 0, tzinfo=timezone.utc)),
        status=AppointmentStatus.SCHEDULED,
        details=None,
        created_at=now,
        updated_at=now,
    )


def test_build_body_sets_customer_attendee_when_email_resolves():
    client = FakeGoogleCalendarClient()
    adapter = GoogleCalendarAdapter(
        client, "cal-1", attendee_email=lambda _customer_id: "cust@example.com"
    )
    adapter.create_event(_appointment(), AppointmentContext(customer_name="John"))
    _cal, body, _send = client.inserted[-1]
    assert body["attendees"] == [
        {"email": "cust@example.com", "responseStatus": "needsAction"}
    ]


def test_build_body_omits_attendee_when_email_is_none():
    client = FakeGoogleCalendarClient()
    adapter = GoogleCalendarAdapter(client, "cal-1", attendee_email=lambda _id: None)
    adapter.create_event(_appointment(), AppointmentContext(customer_name="John"))
    _cal, body, _send = client.inserted[-1]
    assert "attendees" not in body


def test_build_body_lets_guests_modify_the_event():
    client = FakeGoogleCalendarClient()
    adapter = GoogleCalendarAdapter(
        client, "cal-1", attendee_email=lambda _customer_id: "cust@example.com"
    )
    body = adapter._build_body(_appointment(), AppointmentContext())
    assert body["guestsCanModify"] is True


# ---------------------------------------------------------------------------
# insert_event + sendUpdates + 409 duplicate recovery
# ---------------------------------------------------------------------------

def test_create_uses_insert_with_send_updates_all():
    client = FakeGoogleCalendarClient()
    adapter = GoogleCalendarAdapter(client, "cal-1", attendee_email=lambda _id: "c@x.com")
    adapter.create_event(_appointment(), AppointmentContext(customer_name="John"))
    _cal, _body, send_updates = client.inserted[-1]
    assert send_updates == "all"


def test_create_recovers_existing_event_on_duplicate_ical_uid():
    client = FakeGoogleCalendarClient()
    adapter = GoogleCalendarAdapter(client, "cal-1", attendee_email=lambda _id: "c@x.com")
    appt = _appointment()
    first = adapter.create_event(appt, AppointmentContext(customer_name="John"))
    # a crash-retry re-runs create for the same appointment (same deterministic iCalUID)
    second = adapter.create_event(appt, AppointmentContext(customer_name="John"))
    assert first == second == "evt-123"
