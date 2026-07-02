"""Unit tests for the notifications factory's guarded context resolver."""
from __future__ import annotations

import uuid
from dataclasses import dataclass


class _RaisingSession:
    """Stands in for a SQLAlchemy session whose get() always fails."""

    def get(self, *args, **kwargs):
        raise RuntimeError("db down")


class _NoSmtpSettings:
    """Settings stub with SMTP unconfigured, forcing the LoggingEmailSender fallback."""

    smtp_host = None
    smtp_sender_address = None


@dataclass
class _AppointmentStub:
    id: uuid.UUID
    service_call_id: uuid.UUID
    customer_id: uuid.UUID


def test_context_resolver_degrades_to_empty_context_and_logs_errors_on_lookup_failure(
    caplog,
) -> None:
    import logging

    from fsm.platform.notifications_factory import build_notifications

    port = build_notifications(session=_RaisingSession(), settings=_NoSmtpSettings())
    appointment = _AppointmentStub(
        id=uuid.uuid4(), service_call_id=uuid.uuid4(), customer_id=uuid.uuid4()
    )

    with caplog.at_level(logging.ERROR):
        context = port._context_resolver(appointment)

    assert context.customer_name is None
    assert context.problem_description is None
    assert context.service_address is None
    assert context.customer_phone is None
    messages = [r.getMessage() for r in caplog.records]
    assert any(str(appointment.service_call_id) in m for m in messages)
    assert any(str(appointment.customer_id) in m for m in messages)
    assert all(r.exc_info is not None for r in caplog.records)
