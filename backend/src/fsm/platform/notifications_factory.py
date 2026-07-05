"""Factory for constructing the delivering NotificationPort.

Builds a DeliveringNotificationPort wired to the caller's SQLAlchemy session
so that feed writes participate in the same transaction as the appointment change.
SMTP is used when a host and a sender account are configured (smtp_sender_address,
which defaults to the SMTP login); otherwise the LoggingEmailSender fallback is used
so the in-app feed still works without an SMTP server.
"""
from __future__ import annotations

import logging
import uuid
import zoneinfo
from datetime import tzinfo

from sqlalchemy.orm import Session

from fsm.notifications.adapters.feed_repository import SqlAlchemyNotificationFeedRepository
from fsm.notifications.adapters.smtp_email_sender import LoggingEmailSender, SmtpEmailSender
from fsm.notifications.application.delivering_notifications import DeliveringNotificationPort
from fsm.notifications.ports.email_sender import EmailSender
from fsm.platform.config import DEFAULT_TIMEZONE
from fsm.platform.context_rendering import required_field
from fsm.platform.identity_lookup import load_user
from fsm.scheduling.adapters.repositories import SqlAlchemyServiceCallRepository
from fsm.scheduling.adapters.working_hours_repository import SqlAlchemyWorkingHoursRepository
from fsm.scheduling.domain.appointment_context import AppointmentContext
from fsm.scheduling.ports.notifications import NotificationPort

_log = logging.getLogger(__name__)


def build_notifications(session: Session, settings) -> NotificationPort:
    """Return a DeliveringNotificationPort bound to `session`.

    The feed repository shares `session` so notification rows are written
    atomically with the appointment mutation that triggered them. Email is
    best-effort and does not affect the transaction outcome. The context
    resolver shares the same session; every appointment is created against an
    existing service call, customer, and technician, so a failed lookup
    indicates corrupt data — required customer-facing fields render as visible
    placeholders (logged as warnings) rather than failing the booking.
    """
    feed_repo = SqlAlchemyNotificationFeedRepository(session)

    sender_address = settings.smtp_sender_address
    email_sender: EmailSender
    if settings.smtp_host and sender_address:
        password = (
            settings.smtp_password.get_secret_value()
            if settings.smtp_password is not None
            else None
        )
        email_sender = SmtpEmailSender(
            host=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=password,
            from_addr=sender_address,
            use_tls=settings.smtp_use_tls,
        )
    else:
        email_sender = LoggingEmailSender()

    def recipient_email(user_id: uuid.UUID) -> str | None:
        user = load_user(session, user_id)
        return user.email if user else None

    def local_zone(technician_id: uuid.UUID) -> tzinfo:
        """Zone notification times render in: the technician's stored timezone, else the
        region default. Degrades to the default (logged) so a timezone-read failure can
        never block the notification."""
        try:
            stored = SqlAlchemyWorkingHoursRepository(session).get_timezone(technician_id)
            return zoneinfo.ZoneInfo(stored or DEFAULT_TIMEZONE)
        except Exception:
            _log.exception(
                "Timezone lookup failed for technician_id=%s; using %s",
                technician_id,
                DEFAULT_TIMEZONE,
            )
            return zoneinfo.ZoneInfo(DEFAULT_TIMEZONE)

    def appointment_context(appointment) -> AppointmentContext:
        try:
            problem = (
                SqlAlchemyServiceCallRepository(session)
                .get(appointment.service_call_id)
                .description
            )
        except Exception:
            _log.exception(
                "Service call lookup failed for appointment_id=%s service_call_id=%s",
                appointment.id,
                appointment.service_call_id,
            )
            problem = None
        customer = load_user(session, appointment.customer_id)
        technician = load_user(session, appointment.technician_id)
        # Every field is required on this surface: booking rejects a customer without a phone and
        # address, so a missing value here means a failed lookup or a post-booking profile clear —
        # both render as a placeholder plus a warning rather than dropping silently.
        return AppointmentContext(
            customer_name=required_field(customer.preferred_name if customer else None, "customer name"),
            problem_description=required_field(problem, "problem"),
            service_address=required_field(customer.address if customer else None, "service address"),
            customer_phone=required_field(customer.phone if customer else None, "customer phone"),
            technician_name=required_field(technician.preferred_name if technician else None, "technician name"),
            technician_phone=required_field(technician.phone if technician else None, "technician phone"),
        )

    return DeliveringNotificationPort(
        feed_repo=feed_repo,
        email_sender=email_sender,
        recipient_email=recipient_email,
        context_resolver=appointment_context,
        local_zone=local_zone,
        organizer_address=sender_address,
    )
