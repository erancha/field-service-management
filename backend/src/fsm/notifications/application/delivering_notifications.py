"""Delivering implementation of the scheduling NotificationPort.

Writes an in-app Notification for each affected party (customer + technician)
and attempts email delivery. Email failures are caught and logged so a broken
SMTP configuration can never cause a booking to fail.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Callable

from fsm.notifications.adapters.ics import build_ics
from fsm.notifications.domain.notification import Notification, NotificationKind
from fsm.notifications.ports.email_sender import EmailSender
from fsm.notifications.ports.feed_repository import NotificationFeedRepository

_log = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _format_local(dt: datetime) -> str:
    """Render an appointment time as a human-readable local wall-clock string.

    The appointment start is already tz-aware in its local zone, so it is formatted as-is
    without a UTC offset; the recipient reads the time in their own local terms rather than
    an ISO offset such as +03:00.
    """
    return dt.strftime("%A, %d %B %Y at %H:%M")


def _subject(base: str, context) -> str:
    problem = context.problem_summary()
    return f"{base} — {problem}" if problem else base


def _context_lines(context) -> str:
    """Render the customer/problem block appended to email and feed bodies.

    Returns '' when the context carries nothing so an unenriched body has no dangling
    separator.
    """
    lines = []
    name = (context.customer_name or "").strip()
    problem = (context.problem_description or "").strip()
    if name:
        lines.append(f"Customer: {name}")
    if problem:
        lines.append(f"Problem: {problem}")
    return "\n\n" + "\n".join(lines) if lines else ""


class DeliveringNotificationPort:
    """NotificationPort that writes in-app feed rows and sends email.

    recipient_email resolves a user_id to an email address (or None when the
    user has no address). This callable is injected to avoid importing the
    identity context from within notifications.

    context_resolver maps an appointment to a duck-typed AppointmentContext for enrichment
    (customer name, problem description). The resolver never raises; a failed lookup degrades
    the affected field to None, so the port calls it unguarded.

    organizer_address is the email address used as the ICS ORGANIZER, matching the SMTP From.
    When set, appointment notifications include iTIP invitations (REQUEST for booking/reschedule,
    CANCEL for cancellation); otherwise plain events are sent.

    Feed writes share the caller's transaction via the session-bound feed_repo.
    Email sends are best-effort: any exception is caught and logged so that
    notification failures never propagate into the booking transaction.
    """

    def __init__(
        self,
        feed_repo: NotificationFeedRepository,
        email_sender: EmailSender,
        recipient_email: Callable[[uuid.UUID], str | None],
        context_resolver: Callable[[object], object],
        *,
        organizer_address: str | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._feed_repo = feed_repo
        self._email_sender = email_sender
        self._recipient_email = recipient_email
        self._context_resolver = context_resolver
        self._organizer_address = organizer_address
        self._clock = clock

    # ------------------------------------------------------------------
    # NotificationPort implementation
    # ------------------------------------------------------------------

    def appointment_booked(self, appointment) -> None:
        now = self._clock()
        context = self._context_resolver(appointment)
        subject = _subject("Appointment booked", context)
        body = (
            f"Your appointment has been booked for "
            f"{_format_local(appointment.time_range.start)}.{_context_lines(context)}"
        )
        customer_email = self._recipient_email(appointment.customer_id)
        ics = build_ics(
            appointment, context,
            method="REQUEST", organizer=self._organizer_address, attendee=customer_email,
        )

        self._add_feed(appointment.customer_id, NotificationKind.BOOKED, subject, body, now)
        self._add_feed(appointment.technician_id, NotificationKind.BOOKED, subject, body, now)

        self._send_email(appointment.customer_id, subject, body, ics=ics, email=customer_email)
        self._send_email(appointment.technician_id, subject, body, ics=None)

    def appointment_rescheduled(self, appointment) -> None:
        now = self._clock()
        context = self._context_resolver(appointment)
        subject = _subject("Appointment rescheduled", context)
        body = (
            f"Your appointment has been rescheduled to "
            f"{_format_local(appointment.time_range.start)}.{_context_lines(context)}"
        )
        customer_email = self._recipient_email(appointment.customer_id)
        ics = build_ics(
            appointment, context,
            method="REQUEST", organizer=self._organizer_address, attendee=customer_email,
        )

        self._add_feed(appointment.customer_id, NotificationKind.RESCHEDULED, subject, body, now)
        self._add_feed(appointment.technician_id, NotificationKind.RESCHEDULED, subject, body, now)

        self._send_email(appointment.customer_id, subject, body, ics=ics, email=customer_email)
        self._send_email(appointment.technician_id, subject, body, ics=None)

    def appointment_updated(self, appointment) -> None:
        now = self._clock()
        context = self._context_resolver(appointment)
        subject = _subject("Appointment updated", context)
        context_block = _context_lines(context)
        details = (appointment.details or "").strip()
        details_block = (
            ("\n" if context_block else "\n\n") + f"Details: {details}" if details else ""
        )
        body = (
            f"Your appointment for {_format_local(appointment.time_range.start)} "
            f"has been updated.{context_block}{details_block}"
        )
        customer_email = self._recipient_email(appointment.customer_id)
        ics = build_ics(
            appointment, context,
            method="REQUEST", organizer=self._organizer_address, attendee=customer_email,
        )

        self._add_feed(appointment.customer_id, NotificationKind.UPDATED, subject, body, now)
        self._add_feed(appointment.technician_id, NotificationKind.UPDATED, subject, body, now)

        self._send_email(appointment.customer_id, subject, body, ics=ics, email=customer_email)
        self._send_email(appointment.technician_id, subject, body, ics=None)

    def appointment_cancelled(self, appointment) -> None:
        now = self._clock()
        context = self._context_resolver(appointment)
        subject = _subject("Appointment cancelled", context)
        body = f"Your appointment has been cancelled.{_context_lines(context)}"
        customer_email = self._recipient_email(appointment.customer_id)
        ics = build_ics(
            appointment, context,
            method="CANCEL", organizer=self._organizer_address, attendee=customer_email,
        )

        self._add_feed(appointment.customer_id, NotificationKind.CANCELLED, subject, body, now)
        self._add_feed(appointment.technician_id, NotificationKind.CANCELLED, subject, body, now)

        self._send_email(appointment.customer_id, subject, body, ics=ics, email=customer_email)
        self._send_email(appointment.technician_id, subject, body, ics=None)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _add_feed(
        self,
        user_id: uuid.UUID,
        kind: NotificationKind,
        subject: str,
        body: str,
        now: datetime,
    ) -> None:
        notification = Notification(
            id=uuid.uuid4(),
            user_id=user_id,
            kind=kind,
            subject=subject,
            body=body,
            created_at=now,
        )
        self._feed_repo.add(notification)

    def _send_email(
        self,
        user_id: uuid.UUID,
        subject: str,
        body: str,
        *,
        ics: str | None,
        email: str | None = None,
    ) -> None:
        try:
            if email is None:
                email = self._recipient_email(user_id)
            if email is None:
                return
            self._email_sender.send(email, subject, body, ics)
        except Exception:
            _log.exception(
                "Email send failed for user_id=%s subject=%r; continuing",
                user_id,
                subject,
            )
