"""Unit tests for DeliveringNotificationPort using fakes."""
from __future__ import annotations

import uuid
import zoneinfo
from dataclasses import dataclass, replace
from datetime import datetime, timezone

import pytest

from fsm.scheduling.domain.appointment_context import AppointmentContext
from fsm.notifications.domain.notification import Notification, NotificationEvent, NotificationKind
from tests.notifications.fakes import FakeEmailSender, RaisingEmailSender


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeFeedRepository:
    """In-memory NotificationFeedRepository for unit tests.

    events records each shared NotificationEvent once; added expands every event into the
    per-recipient Notification read-model rows, so tests can assert both the single-event
    dedup and the per-party fan-out.
    """

    def __init__(self) -> None:
        self.added: list[Notification] = []
        self.events: list[NotificationEvent] = []
        self._store: dict[uuid.UUID, Notification] = {}

    def add_event(self, event: NotificationEvent, user_ids: list[uuid.UUID]) -> None:
        self.events.append(event)
        for user_id in user_ids:
            notification = Notification(
                id=uuid.uuid4(),
                user_id=user_id,
                kind=event.kind,
                subject=event.subject,
                body=event.body,
                created_at=event.created_at,
            )
            self.added.append(notification)
            self._store[notification.id] = notification

    def list_for_user(
        self, user_id: uuid.UUID, *, unread_only: bool = False
    ) -> list[Notification]:
        results = [n for n in self._store.values() if n.user_id == user_id]
        if unread_only:
            results = [n for n in results if not n.read]
        return results

    def mark_read(self, notification_id: uuid.UUID) -> None:
        pass


# ---------------------------------------------------------------------------
# Appointment stub
# ---------------------------------------------------------------------------


@dataclass
class _FakeTimeRange:
    start: datetime
    end: datetime


@dataclass
class _FakeAppointment:
    id: uuid.UUID
    customer_id: uuid.UUID
    technician_id: uuid.UUID
    time_range: _FakeTimeRange
    created_at: datetime
    updated_at: datetime
    details: str | None = None


def _make_appointment(
    customer_id: uuid.UUID | None = None,
    technician_id: uuid.UUID | None = None,
    details: str | None = None,
) -> _FakeAppointment:
    fixed_time = datetime(2025, 6, 10, 9, 0, tzinfo=timezone.utc)
    return _FakeAppointment(
        id=uuid.uuid4(),
        customer_id=customer_id or uuid.uuid4(),
        technician_id=technician_id or uuid.uuid4(),
        time_range=_FakeTimeRange(
            start=datetime(2025, 6, 10, 9, 0, tzinfo=timezone.utc),
            end=datetime(2025, 6, 10, 10, 0, tzinfo=timezone.utc),
        ),
        created_at=fixed_time,
        updated_at=fixed_time,
        details=details,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# The delivery renderer requires every context field, matching the production resolver's
# required_field guarantees; tests derive variants via replace().
_FULL_CTX = AppointmentContext(
    customer_name="Ada Lovelace",
    problem_description="No hot water",
    service_address="12 Main St",
    customer_phone="+972-50-123",
    technician_name="Grace Hopper",
    technician_phone="+972-50-999",
)


def _port(appt, feed_repo, email_sender, emails: dict[uuid.UUID, str], context=_FULL_CTX,
          zone: timezone = timezone.utc):
    from fsm.notifications.application.delivering_notifications import DeliveringNotificationPort

    fixed_time = datetime(2025, 6, 10, 9, 0, tzinfo=timezone.utc)
    return DeliveringNotificationPort(
        feed_repo=feed_repo,
        email_sender=email_sender,
        recipient_email=lambda uid: emails.get(uid),
        context_resolver=lambda _appt: context,
        local_zone=lambda _technician_id: zone,
        clock=lambda: fixed_time,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAppointmentBooked:
    def test_writes_two_feed_rows(self):
        appt = _make_appointment()
        feed = FakeFeedRepository()
        port = _port(appt, feed, FakeEmailSender(), {})

        port.appointment_booked(appt)

        assert len(feed.added) == 2
        user_ids = {n.user_id for n in feed.added}
        assert appt.customer_id in user_ids
        assert appt.technician_id in user_ids

    def test_writes_one_shared_event_for_both_recipients(self):
        appt = _make_appointment()
        feed = FakeFeedRepository()
        port = _port(appt, feed, FakeEmailSender(), {})

        port.appointment_booked(appt)

        assert len(feed.events) == 1
        [event] = feed.events
        assert event.kind == NotificationKind.BOOKED
        assert {n.user_id for n in feed.added} == {appt.customer_id, appt.technician_id}

    def test_body_shows_readable_local_time_not_iso_offset(self):
        appt = _make_appointment()
        email = FakeEmailSender()
        port = _port(appt, FakeFeedRepository(), email, {appt.technician_id: "t@example.com"})

        port.appointment_booked(appt)

        [msg] = email.sent
        assert "Tuesday, 10 June 2025 at 09:00" in msg["body"]
        assert "2025-06-10T09:00:00" not in msg["body"]

    def test_body_converts_utc_stored_start_into_the_resolved_zone(self):
        appt = _make_appointment()  # stored start is 09:00 UTC
        email = FakeEmailSender()
        port = _port(appt, FakeFeedRepository(), email, {appt.technician_id: "t@example.com"},
                     zone=zoneinfo.ZoneInfo("Asia/Jerusalem"))

        port.appointment_booked(appt)

        [msg] = email.sent
        assert "Tuesday, 10 June 2025 at 12:00" in msg["body"]

    def test_sends_one_email_to_the_technician_only(self):
        cust_id = uuid.uuid4()
        tech_id = uuid.uuid4()
        appt = _make_appointment(customer_id=cust_id, technician_id=tech_id)
        feed = FakeFeedRepository()
        sender = FakeEmailSender()
        emails = {cust_id: "customer@example.com", tech_id: "tech@example.com"}

        port = _port(appt, feed, sender, emails)
        port.appointment_booked(appt)

        assert len(sender.sent) == 1
        assert sender.sent[0]["to"] == "tech@example.com"

    def test_all_feed_rows_have_booked_kind(self):
        appt = _make_appointment()
        feed = FakeFeedRepository()
        port = _port(appt, feed, FakeEmailSender(), {})

        port.appointment_booked(appt)

        assert all(n.kind == NotificationKind.BOOKED for n in feed.added)

    def test_email_failure_does_not_raise(self):
        tech_id = uuid.uuid4()
        appt = _make_appointment(technician_id=tech_id)
        feed = FakeFeedRepository()
        emails = {tech_id: "tech@example.com"}

        port = _port(appt, feed, RaisingEmailSender(), emails)
        # Must not raise even though email fails
        port.appointment_booked(appt)

        # Feed writes still happened
        assert len(feed.added) == 2


class TestAppointmentRescheduled:
    def test_writes_two_feed_rows_with_rescheduled_kind(self):
        appt = _make_appointment()
        feed = FakeFeedRepository()
        port = _port(appt, feed, FakeEmailSender(), {})

        port.appointment_rescheduled(appt)

        assert len(feed.added) == 2
        assert all(n.kind == NotificationKind.RESCHEDULED for n in feed.added)

    def test_sends_one_email_to_the_technician_only(self):
        cust_id = uuid.uuid4()
        tech_id = uuid.uuid4()
        appt = _make_appointment(customer_id=cust_id, technician_id=tech_id)
        feed = FakeFeedRepository()
        sender = FakeEmailSender()
        emails = {cust_id: "c@example.com", tech_id: "t@example.com"}

        port = _port(appt, feed, sender, emails)
        port.appointment_rescheduled(appt)

        assert len(sender.sent) == 1
        assert sender.sent[0]["to"] == "t@example.com"


class TestAppointmentCancelled:
    def test_writes_two_feed_rows_with_cancelled_kind(self):
        appt = _make_appointment()
        feed = FakeFeedRepository()
        port = _port(appt, feed, FakeEmailSender(), {})

        port.appointment_cancelled(appt)

        assert len(feed.added) == 2
        assert all(n.kind == NotificationKind.CANCELLED for n in feed.added)

    def test_sends_one_email_to_the_technician_only(self):
        cust_id = uuid.uuid4()
        tech_id = uuid.uuid4()
        appt = _make_appointment(customer_id=cust_id, technician_id=tech_id)
        feed = FakeFeedRepository()
        sender = FakeEmailSender()
        emails = {cust_id: "c@example.com", tech_id: "t@example.com"}

        port = _port(appt, feed, sender, emails)
        port.appointment_cancelled(appt)

        assert len(sender.sent) == 1
        assert sender.sent[0]["to"] == "t@example.com"

    def test_email_failure_does_not_raise(self):
        tech_id = uuid.uuid4()
        appt = _make_appointment(technician_id=tech_id)
        feed = FakeFeedRepository()
        emails = {tech_id: "t@example.com"}

        port = _port(appt, feed, RaisingEmailSender(), emails)
        port.appointment_cancelled(appt)

        assert len(feed.added) == 2


class TestCustomerAttendeeInvitation:
    """The customer's calendar invitation now comes from Google as a guest, not this port."""

    def test_customer_receives_feed_but_no_email(self):
        cust_id = uuid.uuid4()
        tech_id = uuid.uuid4()
        appt = _make_appointment(customer_id=cust_id, technician_id=tech_id)
        feed = FakeFeedRepository()
        sender = FakeEmailSender()
        emails = {cust_id: "customer@example.com", tech_id: "tech@example.com"}

        port = _port(appt, feed, sender, emails)
        port.appointment_booked(appt)

        feed_user_ids = {n.user_id for n in feed.added}
        assert cust_id in feed_user_ids
        assert tech_id in feed_user_ids

        emailed = {m["to"] for m in sender.sent}
        assert "customer@example.com" not in emailed
        assert "tech@example.com" in emailed


class TestNotificationContext:
    def test_booked_subject_leads_with_problem(self):
        appt = _make_appointment()
        sender = FakeEmailSender()
        port = _port(appt, FakeFeedRepository(), sender, {appt.technician_id: "t@example.com"})

        port.appointment_booked(appt)

        [msg] = sender.sent
        assert msg["subject"] == "Appointment booked — No hot water"

    def test_booked_body_names_technician_between_customer_and_problem(self):
        appt = _make_appointment()
        sender = FakeEmailSender()
        port = _port(appt, FakeFeedRepository(), sender, {appt.technician_id: "t@example.com"})

        port.appointment_booked(appt)

        [msg] = sender.sent
        body = msg["body"]
        assert "Technician: Grace Hopper" in body
        assert "Technician phone: +972-50-999" in body
        assert body.index("Customer:") < body.index("Technician:") < body.index("Problem:")

    def test_booked_body_names_customer_and_problem_without_bare_id(self):
        appt = _make_appointment()
        sender = FakeEmailSender()
        port = _port(appt, FakeFeedRepository(), sender, {appt.technician_id: "t@example.com"})

        port.appointment_booked(appt)

        [msg] = sender.sent
        assert "Customer: Ada Lovelace" in msg["body"]
        assert "Problem: No hot water" in msg["body"]
        assert str(appt.id) not in msg["body"]

    @pytest.mark.parametrize("field, label", [
        ("customer_name", "Customer"),
        ("customer_phone", "Phone"),
        ("service_address", "Address"),
        ("technician_name", "Technician"),
        ("technician_phone", "Technician phone"),
        ("problem_description", "Problem"),
    ])
    def test_blank_required_context_field_raises_instead_of_dropping_the_line(
        self, field, label
    ):
        appt = _make_appointment()
        ctx = replace(_FULL_CTX, **{field: None})
        port = _port(appt, FakeFeedRepository(), FakeEmailSender(),
                     {appt.technician_id: "t@example.com"}, context=ctx)

        with pytest.raises(ValueError, match=f"field: {label}"):
            port.appointment_booked(appt)

    def test_feed_rows_carry_enriched_subject(self):
        appt = _make_appointment()
        feed = FakeFeedRepository()
        port = _port(appt, feed, FakeEmailSender(), {})

        port.appointment_booked(appt)

        assert all(n.subject == "Appointment booked — No hot water" for n in feed.added)

    def test_bodies_include_customer_phone_and_address(self):
        appt = _make_appointment()
        sender = FakeEmailSender()
        feed = FakeFeedRepository()
        port = _port(appt, feed, sender, {appt.technician_id: "t@example.com"})

        port.appointment_booked(appt)
        port.appointment_rescheduled(appt)
        port.appointment_cancelled(appt)

        assert len(sender.sent) == 3
        assert all("Phone: +972-50-123" in m["body"] for m in sender.sent)
        assert all("Address: 12 Main St" in m["body"] for m in sender.sent)
        assert all("Phone: +972-50-123" in n.body for n in feed.added)
        assert all("Address: 12 Main St" in n.body for n in feed.added)

    def test_rescheduled_and_cancelled_bodies_carry_context(self):
        appt = _make_appointment()
        sender = FakeEmailSender()
        emails = {appt.technician_id: "t@example.com"}

        port = _port(appt, FakeFeedRepository(), sender, emails)
        port.appointment_rescheduled(appt)
        port.appointment_cancelled(appt)

        assert len(sender.sent) == 2
        assert all("Problem: No hot water" in m["body"] for m in sender.sent)
        assert sender.sent[0]["subject"] == "Appointment rescheduled — No hot water"
        assert sender.sent[1]["subject"] == "Appointment cancelled — No hot water"


class TestAppointmentUpdated:
    def test_writes_two_feed_rows_with_updated_kind(self):
        appt = _make_appointment(details="Gate code 4321")
        feed = FakeFeedRepository()
        port = _port(appt, feed, FakeEmailSender(), {})

        port.appointment_updated(appt)

        assert len(feed.added) == 2
        assert {n.user_id for n in feed.added} == {appt.customer_id, appt.technician_id}
        assert all(n.kind == NotificationKind.UPDATED for n in feed.added)

    def test_body_carries_the_details_and_subject_says_updated(self):
        appt = _make_appointment(details="Gate code 4321")
        sender = FakeEmailSender()
        port = _port(appt, FakeFeedRepository(), sender,
                     {appt.technician_id: "t@example.com"})

        port.appointment_updated(appt)

        [msg] = sender.sent
        assert msg["subject"].startswith("Appointment updated")
        assert "has been updated" in msg["body"]
        assert "Details: Gate code 4321" in msg["body"]


class TestAppointmentRescheduleRejected:
    def test_writes_two_feed_rows_with_rejected_kind(self):
        appt = _make_appointment()
        feed = FakeFeedRepository()
        port = _port(appt, feed, FakeEmailSender(), {})

        port.appointment_reschedule_rejected(appt)

        assert len(feed.added) == 2
        assert all(n.kind == NotificationKind.RESCHEDULE_REJECTED for n in feed.added)

    def test_sends_one_email_to_the_technician_only_with_kept_time(self):
        cust_id = uuid.uuid4()
        tech_id = uuid.uuid4()
        appt = _make_appointment(customer_id=cust_id, technician_id=tech_id)
        feed = FakeFeedRepository()
        sender = FakeEmailSender()
        emails = {cust_id: "c@example.com", tech_id: "t@example.com"}

        port = _port(appt, feed, sender, emails)
        port.appointment_reschedule_rejected(appt)

        assert len(sender.sent) == 1
        assert sender.sent[0]["to"] == "t@example.com"
        assert sender.sent[0]["subject"].startswith("Appointment time change rejected")
        assert "The requested time is not available. The appointment remains at" in (
            sender.sent[0]["body"]
        )
