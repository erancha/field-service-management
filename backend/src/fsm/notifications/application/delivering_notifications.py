"""Delivering implementation of the scheduling NotificationPort.

Writes an in-app Notification for each affected party (customer + technician) and attempts
email delivery to the technician. The customer's calendar invitation is delivered by Google as
a guest on the appointment's calendar event, so this port never emails the customer. Email
failures are caught and logged so a broken SMTP configuration can never cause a booking to fail.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone, tzinfo
from typing import Callable

from fsm.notifications.domain.notification import Notification, NotificationKind
from fsm.notifications.ports.appointment_context import AppointmentContextView
from fsm.notifications.ports.email_sender import EmailSender
from fsm.notifications.ports.feed_repository import NotificationFeedRepository

_log = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _format_local(dt: datetime, zone: tzinfo) -> str:
    """Render an appointment time as a human-readable wall-clock string in `zone`.

    Appointment datetimes are tz-aware but arrive in whatever zone produced them (the client's
    offset on booking, UTC when loaded from the database), so the explicit conversion is what
    guarantees the recipient reads a correct local time with no ISO offset attached.
    """
    return dt.astimezone(zone).strftime("%A, %d %B %Y at %H:%M")


def _subject(base: str, context: AppointmentContextView) -> str:
    problem = context.problem_summary()
    return f"{base} — {problem}" if problem else base


def _required_line(label: str, value: str | None) -> str:
    """Render "label: value" for a field the resolver contract guarantees non-blank.

    The notifications resolver substitutes a visible placeholder when the underlying data is
    missing, so a None or blank value here is a wiring bug — raising beats a quietly shorter body.
    """
    if value is None or not value.strip():
        raise ValueError(f"Appointment context is missing required field: {label}")
    return f"{label}: {value}"


def _context_lines(context: AppointmentContextView) -> str:
    """Render the customer/problem block appended to email and feed bodies.

    Every rendered field is required on this surface (booking enforces the customer's phone and
    address), so the block is always present and complete.
    """
    lines = [
        _required_line("Customer", context.customer_name),
        _required_line("Phone", context.customer_phone),
        _required_line("Address", context.service_address),
        _required_line("Technician", context.technician_name),
        _required_line("Technician phone", context.technician_phone),
        _required_line("Problem", context.problem_description),
    ]
    return "\n\n" + "\n".join(lines)


class DeliveringNotificationPort:
    """NotificationPort that writes in-app feed rows and emails the technician.

    recipient_email resolves a user_id to an email address (or None when the
    user has no address). This callable is injected to avoid importing the
    identity context from within notifications.

    context_resolver maps an appointment to an AppointmentContextView for enrichment. The
    resolver never raises: a failed lookup yields a visible placeholder for fields required on
    this surface and None for optional ones, so the port calls it unguarded.

    local_zone maps the appointment's technician_id to the timezone bodies render times in. An
    appointment is a physical visit, so one zone — the technician's service region — is correct
    for both parties.

    The customer receives an in-app feed row only: their calendar invitation is delivered by
    Google as a guest on the appointment's Google Calendar event, not by this port.

    Feed writes share the caller's transaction via the session-bound feed_repo.
    Email sends are best-effort: any exception is caught and logged so that
    notification failures never propagate into the booking transaction.
    """

    def __init__(
        self,
        feed_repo: NotificationFeedRepository,
        email_sender: EmailSender,
        recipient_email: Callable[[uuid.UUID], str | None],
        context_resolver: Callable[[object], AppointmentContextView],
        *,
        local_zone: Callable[[uuid.UUID], tzinfo],
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._feed_repo = feed_repo
        self._email_sender = email_sender
        self._recipient_email = recipient_email
        self._context_resolver = context_resolver
        self._local_zone = local_zone
        self._clock = clock

    def _start_text(self, appointment) -> str:
        return _format_local(
            appointment.time_range.start, self._local_zone(appointment.technician_id)
        )

    # ------------------------------------------------------------------
    # NotificationPort implementation
    # ------------------------------------------------------------------

    def appointment_booked(self, appointment) -> None:
        self._deliver(
            appointment,
            kind=NotificationKind.BOOKED,
            subject_base="Appointment booked",
            body=lambda context: (
                f"Your appointment has been booked for "
                f"{self._start_text(appointment)}.{_context_lines(context)}"
            ),
        )

    def appointment_rescheduled(self, appointment) -> None:
        self._deliver(
            appointment,
            kind=NotificationKind.RESCHEDULED,
            subject_base="Appointment rescheduled",
            body=lambda context: (
                f"Your appointment has been rescheduled to "
                f"{self._start_text(appointment)}.{_context_lines(context)}"
            ),
        )

    def appointment_reschedule_rejected(self, appointment) -> None:
        self._deliver(
            appointment,
            kind=NotificationKind.RESCHEDULE_REJECTED,
            subject_base="Appointment time change rejected",
            body=lambda context: (
                f"The requested time is not available. The appointment remains at "
                f"{self._start_text(appointment)}.{_context_lines(context)}"
            ),
        )

    def appointment_updated(self, appointment) -> None:
        details = appointment.details
        details_block = (
            f"\nDetails: {details.strip()}" if details is not None and details.strip() else ""
        )
        self._deliver(
            appointment,
            kind=NotificationKind.UPDATED,
            subject_base="Appointment updated",
            body=lambda context: (
                f"Your appointment for {self._start_text(appointment)} "
                f"has been updated.{_context_lines(context)}{details_block}"
            ),
        )

    def appointment_cancelled(self, appointment) -> None:
        self._deliver(
            appointment,
            kind=NotificationKind.CANCELLED,
            subject_base="Appointment cancelled",
            body=lambda context: f"Your appointment has been cancelled.{_context_lines(context)}",
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _deliver(
        self,
        appointment,
        *,
        kind: NotificationKind,
        subject_base: str,
        body: Callable[[AppointmentContextView], str],
    ) -> None:
        """Run the shared delivery sequence for one appointment lifecycle event.

        Both parties receive the same subject and body as a feed entry; only the technician
        also gets an email. The customer's calendar invitation is delivered by Google as a
        guest on the appointment's calendar event.
        """
        now = self._clock()
        context = self._context_resolver(appointment)
        subject = _subject(subject_base, context)
        rendered_body = body(context)

        self._add_feed(appointment.customer_id, kind, subject, rendered_body, now)
        self._add_feed(appointment.technician_id, kind, subject, rendered_body, now)

        self._send_email(appointment.technician_id, subject, rendered_body)

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

    def _send_email(self, user_id: uuid.UUID, subject: str, body: str) -> None:
        try:
            email = self._recipient_email(user_id)
            if email is None:
                return
            self._email_sender.send(email, subject, body)
        except Exception:
            _log.exception(
                "Email send failed for user_id=%s subject=%r; continuing",
                user_id,
                subject,
            )
