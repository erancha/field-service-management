"""Unit tests for DeliveringNotificationPort using fakes."""
from __future__ import annotations

import uuid
import zoneinfo
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from fsm.scheduling.domain.appointment_context import AppointmentContext
from fsm.notifications.domain.notification import Notification, NotificationKind
from fsm.notifications.ports.feed_repository import NotificationFeedRepository
from fsm.notifications.ports.email_sender import EmailSender


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeFeedRepository:
    """In-memory NotificationFeedRepository for unit tests."""

    def __init__(self) -> None:
        self.added: list[Notification] = []
        self._store: dict[uuid.UUID, Notification] = {}

    def add(self, notification: Notification) -> None:
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


class FakeEmailSender:
    """In-memory EmailSender that records calls."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    def send(
        self,
        to: str,
        subject: str,
        body: str,
        ics: str | None = None,
    ) -> None:
        self.sent.append({"to": to, "subject": subject, "body": body, "ics": ics})


class RaisingEmailSender:
    """EmailSender that always raises — used to verify booking-safety."""

    def send(self, to: str, subject: str, body: str, ics: str | None = None) -> None:
        raise RuntimeError("SMTP unavailable")


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


def _port(appt, feed_repo, email_sender, emails: dict[uuid.UUID, str], context=None,
          organizer="ops@fsm.example", zone: timezone = timezone.utc):
    from fsm.notifications.application.delivering_notifications import DeliveringNotificationPort

    fixed_time = datetime(2025, 6, 10, 9, 0, tzinfo=timezone.utc)
    return DeliveringNotificationPort(
        feed_repo=feed_repo,
        email_sender=email_sender,
        recipient_email=lambda uid: emails.get(uid),
        context_resolver=lambda _appt: context if context is not None else AppointmentContext(),
        local_zone=lambda _technician_id: zone,
        organizer_address=organizer,
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

    def test_body_shows_readable_local_time_not_iso_offset(self):
        appt = _make_appointment()
        email = FakeEmailSender()
        port = _port(appt, FakeFeedRepository(), email, {appt.customer_id: "c@example.com"})

        port.appointment_booked(appt)

        [msg] = [m for m in email.sent if m["to"] == "c@example.com"]
        assert "Tuesday, 10 June 2025 at 09:00" in msg["body"]
        assert "2025-06-10T09:00:00" not in msg["body"]

    def test_body_converts_utc_stored_start_into_the_resolved_zone(self):
        appt = _make_appointment()  # stored start is 09:00 UTC
        email = FakeEmailSender()
        port = _port(appt, FakeFeedRepository(), email, {appt.customer_id: "c@example.com"},
                     zone=zoneinfo.ZoneInfo("Asia/Jerusalem"))

        port.appointment_booked(appt)

        [msg] = [m for m in email.sent if m["to"] == "c@example.com"]
        assert "Tuesday, 10 June 2025 at 12:00" in msg["body"]

    def test_sends_two_emails_when_both_have_addresses(self):
        cust_id = uuid.uuid4()
        tech_id = uuid.uuid4()
        appt = _make_appointment(customer_id=cust_id, technician_id=tech_id)
        feed = FakeFeedRepository()
        sender = FakeEmailSender()
        emails = {cust_id: "customer@example.com", tech_id: "tech@example.com"}

        port = _port(appt, feed, sender, emails)
        port.appointment_booked(appt)

        assert len(sender.sent) == 2
        recipients = {m["to"] for m in sender.sent}
        assert "customer@example.com" in recipients
        assert "tech@example.com" in recipients

    def test_customer_email_includes_ics(self):
        cust_id = uuid.uuid4()
        tech_id = uuid.uuid4()
        appt = _make_appointment(customer_id=cust_id, technician_id=tech_id)
        feed = FakeFeedRepository()
        sender = FakeEmailSender()
        emails = {cust_id: "customer@example.com", tech_id: "tech@example.com"}

        port = _port(appt, feed, sender, emails)
        port.appointment_booked(appt)

        cust_email = next(m for m in sender.sent if m["to"] == "customer@example.com")
        tech_email = next(m for m in sender.sent if m["to"] == "tech@example.com")
        assert cust_email["ics"] is not None
        assert "BEGIN:VCALENDAR" in cust_email["ics"]
        assert tech_email["ics"] is None

    def test_all_feed_rows_have_booked_kind(self):
        appt = _make_appointment()
        feed = FakeFeedRepository()
        port = _port(appt, feed, FakeEmailSender(), {})

        port.appointment_booked(appt)

        assert all(n.kind == NotificationKind.BOOKED for n in feed.added)

    def test_email_failure_does_not_raise(self):
        cust_id = uuid.uuid4()
        appt = _make_appointment(customer_id=cust_id)
        feed = FakeFeedRepository()
        emails = {cust_id: "customer@example.com"}

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

    def test_sends_emails_to_both(self):
        cust_id = uuid.uuid4()
        tech_id = uuid.uuid4()
        appt = _make_appointment(customer_id=cust_id, technician_id=tech_id)
        feed = FakeFeedRepository()
        sender = FakeEmailSender()
        emails = {cust_id: "c@example.com", tech_id: "t@example.com"}

        port = _port(appt, feed, sender, emails)
        port.appointment_rescheduled(appt)

        assert len(sender.sent) == 2

    def test_customer_reschedule_email_includes_ics(self):
        cust_id = uuid.uuid4()
        tech_id = uuid.uuid4()
        appt = _make_appointment(customer_id=cust_id, technician_id=tech_id)
        feed = FakeFeedRepository()
        sender = FakeEmailSender()
        emails = {cust_id: "c@example.com", tech_id: "t@example.com"}

        port = _port(appt, feed, sender, emails)
        port.appointment_rescheduled(appt)

        cust_email = next(m for m in sender.sent if m["to"] == "c@example.com")
        assert cust_email["ics"] is not None


class TestAppointmentCancelled:
    def test_writes_two_feed_rows_with_cancelled_kind(self):
        appt = _make_appointment()
        feed = FakeFeedRepository()
        port = _port(appt, feed, FakeEmailSender(), {})

        port.appointment_cancelled(appt)

        assert len(feed.added) == 2
        assert all(n.kind == NotificationKind.CANCELLED for n in feed.added)

    def test_sends_emails_to_both(self):
        cust_id = uuid.uuid4()
        tech_id = uuid.uuid4()
        appt = _make_appointment(customer_id=cust_id, technician_id=tech_id)
        feed = FakeFeedRepository()
        sender = FakeEmailSender()
        emails = {cust_id: "c@example.com", tech_id: "t@example.com"}

        port = _port(appt, feed, sender, emails)
        port.appointment_cancelled(appt)

        assert len(sender.sent) == 2

    def test_email_failure_does_not_raise(self):
        cust_id = uuid.uuid4()
        appt = _make_appointment(customer_id=cust_id)
        feed = FakeFeedRepository()
        emails = {cust_id: "c@example.com"}

        port = _port(appt, feed, RaisingEmailSender(), emails)
        port.appointment_cancelled(appt)

        assert len(feed.added) == 2


class TestNotificationContext:
    _CTX = AppointmentContext(customer_name="Ada Lovelace", problem_description="No hot water")

    def test_booked_subject_leads_with_problem(self):
        appt = _make_appointment()
        sender = FakeEmailSender()
        port = _port(appt, FakeFeedRepository(), sender, {appt.customer_id: "c@example.com"},
                     context=self._CTX)

        port.appointment_booked(appt)

        [msg] = [m for m in sender.sent if m["to"] == "c@example.com"]
        assert msg["subject"] == "Appointment booked — No hot water"

    def test_booked_body_names_technician_between_customer_and_problem(self):
        appt = _make_appointment()
        sender = FakeEmailSender()
        ctx = AppointmentContext(
            customer_name="Ada Lovelace",
            problem_description="No hot water",
            technician_name="Grace Hopper",
            technician_phone="+972-50-999",
        )
        port = _port(appt, FakeFeedRepository(), sender, {appt.customer_id: "c@example.com"},
                     context=ctx)

        port.appointment_booked(appt)

        [msg] = [m for m in sender.sent if m["to"] == "c@example.com"]
        body = msg["body"]
        assert "Technician: Grace Hopper" in body
        assert "Technician phone: +972-50-999" in body
        assert body.index("Customer:") < body.index("Technician:") < body.index("Problem:")

    def test_booked_body_names_customer_and_problem_without_bare_id(self):
        appt = _make_appointment()
        sender = FakeEmailSender()
        port = _port(appt, FakeFeedRepository(), sender, {appt.customer_id: "c@example.com"},
                     context=self._CTX)

        port.appointment_booked(appt)

        [msg] = [m for m in sender.sent if m["to"] == "c@example.com"]
        assert "Customer: Ada Lovelace" in msg["body"]
        assert "Problem: No hot water" in msg["body"]
        assert str(appt.id) not in msg["body"]

    def test_booked_ics_carries_context(self):
        appt = _make_appointment()
        sender = FakeEmailSender()
        port = _port(appt, FakeFeedRepository(), sender, {appt.customer_id: "c@example.com"},
                     context=self._CTX)

        port.appointment_booked(appt)

        [msg] = [m for m in sender.sent if m["to"] == "c@example.com"]
        assert "SUMMARY:Ada Lovelace — No hot water" in msg["ics"]

    def test_empty_context_keeps_generic_subject_and_clean_body(self):
        appt = _make_appointment()
        sender = FakeEmailSender()
        port = _port(appt, FakeFeedRepository(), sender, {appt.customer_id: "c@example.com"})

        port.appointment_booked(appt)

        [msg] = [m for m in sender.sent if m["to"] == "c@example.com"]
        assert msg["subject"] == "Appointment booked"
        assert "Customer:" not in msg["body"]
        assert "Problem:" not in msg["body"]

    def test_feed_rows_carry_enriched_subject(self):
        appt = _make_appointment()
        feed = FakeFeedRepository()
        port = _port(appt, feed, FakeEmailSender(), {}, context=self._CTX)

        port.appointment_booked(appt)

        assert all(n.subject == "Appointment booked — No hot water" for n in feed.added)

    def test_rescheduled_and_cancelled_bodies_carry_context(self):
        appt = _make_appointment()
        sender = FakeEmailSender()
        emails = {appt.customer_id: "c@example.com"}

        port = _port(appt, FakeFeedRepository(), sender, emails, context=self._CTX)
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

    def test_customer_email_carries_a_request_ics_and_technician_none(self):
        cust_id, tech_id = uuid.uuid4(), uuid.uuid4()
        appt = _make_appointment(customer_id=cust_id, technician_id=tech_id,
                                 details="Gate code 4321")
        sender = FakeEmailSender()
        port = _port(appt, FakeFeedRepository(), sender,
                     {cust_id: "cara@example.com", tech_id: "t@example.com"})

        port.appointment_updated(appt)

        cust = next(m for m in sender.sent if m["to"] == "cara@example.com")
        tech = next(m for m in sender.sent if m["to"] == "t@example.com")
        assert "METHOD:REQUEST" in cust["ics"]
        assert tech["ics"] is None

    def test_body_carries_the_details_and_subject_says_updated(self):
        appt = _make_appointment(details="Gate code 4321")
        sender = FakeEmailSender()
        port = _port(appt, FakeFeedRepository(), sender,
                     {appt.customer_id: "cara@example.com"})

        port.appointment_updated(appt)

        [msg] = [m for m in sender.sent if m["to"] == "cara@example.com"]
        assert msg["subject"].startswith("Appointment updated")
        assert "has been updated" in msg["body"]
        assert "Details: Gate code 4321" in msg["body"]

    def test_ics_description_carries_the_details(self):
        appt = _make_appointment(details="Gate code 4321")
        sender = FakeEmailSender()
        port = _port(appt, FakeFeedRepository(), sender,
                     {appt.customer_id: "cara@example.com"})

        port.appointment_updated(appt)

        [msg] = [m for m in sender.sent if m["to"] == "cara@example.com"]
        ics_unfolded = msg["ics"].replace("\r\n ", "")
        assert "DESCRIPTION:Gate code 4321" in ics_unfolded


class TestIcsInvitation:
    def test_booked_customer_ics_is_a_request_addressed_to_the_customer(self):
        cust_id = uuid.uuid4()
        appt = _make_appointment(customer_id=cust_id)
        sender = FakeEmailSender()
        port = _port(appt, FakeFeedRepository(), sender, {cust_id: "cara@example.com"})

        port.appointment_booked(appt)

        cust = next(m for m in sender.sent if m["to"] == "cara@example.com")
        assert "METHOD:REQUEST" in cust["ics"]
        assert "ORGANIZER:mailto:ops@fsm.example" in cust["ics"]
        assert "ATTENDEE" in cust["ics"]
        ics_unfolded = cust["ics"].replace("\r\n ", "")
        assert "cara@example.com" in ics_unfolded

    def test_cancel_now_attaches_a_cancel_ics_for_the_customer_only(self):
        cust_id, tech_id = uuid.uuid4(), uuid.uuid4()
        appt = _make_appointment(customer_id=cust_id, technician_id=tech_id)
        sender = FakeEmailSender()
        port = _port(appt, FakeFeedRepository(), sender,
                     {cust_id: "cara@example.com", tech_id: "t@example.com"})

        port.appointment_cancelled(appt)

        cust = next(m for m in sender.sent if m["to"] == "cara@example.com")
        tech = next(m for m in sender.sent if m["to"] == "t@example.com")
        assert "METHOD:CANCEL" in cust["ics"]
        assert tech["ics"] is None
