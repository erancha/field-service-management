"""No-op and logging adapters for development and testing without external services.

These adapters satisfy the scheduling port protocols without requiring Google
Calendar credentials or a real notification provider.
"""
from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID, uuid4

from fsm.scheduling.domain.appointment import Appointment
from fsm.scheduling.domain.appointment_context import AppointmentContext
from fsm.scheduling.domain.time_range import TimeRange
from fsm.scheduling.ports.calendar import CalendarPort
from fsm.scheduling.ports.notifications import NotificationPort

_log = logging.getLogger(__name__)


class NullCalendarPort:
    """CalendarPort that returns no busy intervals and silently discards event operations.

    Satisfies the CalendarPort protocol for environments where Google Calendar
    is not configured. create_event returns a synthetic event id so the outbox
    dispatcher can set external_event_id without failing.
    """

    def get_busy(
        self,
        technician_id: UUID,
        start: datetime,
        end: datetime,
    ) -> list[TimeRange]:
        return []

    def create_event(self, appointment: Appointment, context: AppointmentContext) -> str:
        return f"null-evt-{uuid4()}"

    def update_event(self, external_event_id: str, appointment: Appointment, context: AppointmentContext) -> None:
        pass

    def delete_event(self, external_event_id: str) -> None:
        pass


# Structural check: NullCalendarPort must satisfy the CalendarPort protocol.
assert isinstance(NullCalendarPort(), CalendarPort)


class LoggingNotificationPort:
    """NotificationPort that records each lifecycle event via the standard logging system.

    Satisfies the NotificationPort protocol for development, staging, or any
    environment where real push/email/SMS notifications are not required.
    """

    def appointment_booked(self, appointment: Appointment) -> None:
        _log.info(
            "Notification — appointment_booked: appointment_id=%s customer_id=%s technician_id=%s start=%s",
            appointment.id,
            appointment.customer_id,
            appointment.technician_id,
            appointment.time_range.start.isoformat(),
        )

    def appointment_rescheduled(self, appointment: Appointment) -> None:
        _log.info(
            "Notification — appointment_rescheduled: appointment_id=%s new_start=%s",
            appointment.id,
            appointment.time_range.start.isoformat(),
        )

    def appointment_cancelled(self, appointment: Appointment) -> None:
        _log.info(
            "Notification — appointment_cancelled: appointment_id=%s",
            appointment.id,
        )


# Structural check: LoggingNotificationPort must satisfy the NotificationPort protocol.
assert isinstance(LoggingNotificationPort(), NotificationPort)
