"""Factory for constructing the delivering NotificationPort.

Builds a DeliveringNotificationPort wired to the caller's SQLAlchemy session
so that feed writes participate in the same transaction as the appointment change.
SMTP is used when smtp_host and smtp_from are both configured; otherwise the
LoggingEmailSender fallback is used so the in-app feed still works without an
SMTP server.
"""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from fsm.notifications.adapters.feed_repository import SqlAlchemyNotificationFeedRepository
from fsm.notifications.adapters.smtp_email_sender import LoggingEmailSender, SmtpEmailSender
from fsm.notifications.application.delivering_notifications import DeliveringNotificationPort
from fsm.scheduling.ports.notifications import NotificationPort


def build_notifications(session: Session, settings) -> NotificationPort:
    """Return a DeliveringNotificationPort bound to `session`.

    The feed repository shares `session` so notification rows are written
    atomically with the appointment mutation that triggered them. Email is
    best-effort and does not affect the transaction outcome.
    """
    feed_repo = SqlAlchemyNotificationFeedRepository(session)

    if settings.smtp_host and settings.smtp_from:
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
            from_addr=settings.smtp_from,
            use_tls=settings.smtp_use_tls,
        )
    else:
        email_sender = LoggingEmailSender()

    def recipient_email(user_id: uuid.UUID) -> str | None:
        from fsm.identity.adapters.repositories import SqlAlchemyUserRepository

        try:
            repo = SqlAlchemyUserRepository(session)
            user = repo.get(user_id)
            return user.email
        except Exception:
            return None

    return DeliveringNotificationPort(
        feed_repo=feed_repo,
        email_sender=email_sender,
        recipient_email=recipient_email,
    )
