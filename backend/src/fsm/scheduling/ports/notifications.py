"""Notification port definition for the scheduling bounded context.

Defines the outbound interface for dispatching appointment lifecycle notifications.
The domain layer depends only on this protocol; adapters supply the concrete
implementation (email, SMS, push, etc.).
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from fsm.scheduling.domain.appointment import Appointment


@runtime_checkable
class NotificationPort(Protocol):
    """Outbound interface for appointment lifecycle notifications."""

    def appointment_booked(self, appointment: Appointment) -> None:
        """Notify relevant parties that a new appointment has been booked."""
        ...

    def appointment_rescheduled(self, appointment: Appointment) -> None:
        """Notify relevant parties that an appointment has been rescheduled."""
        ...

    def appointment_reschedule_rejected(self, appointment: Appointment) -> None:
        """Notify relevant parties that a requested time change was rejected and reverted."""
        ...

    def appointment_updated(self, appointment: Appointment) -> None:
        """Notify relevant parties that an appointment's content changed without moving in time."""
        ...

    def appointment_cancelled(self, appointment: Appointment) -> None:
        """Notify relevant parties that an appointment has been cancelled."""
        ...
