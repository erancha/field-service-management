"""Outbound port boundary for the scheduling bounded context.

Ports define the boundary between the domain and its infrastructure adapters,
covering persistence, calendar projection, notifications, and the unit of work
that owns a transaction. Every protocol re-exported here is @runtime_checkable so
adapters can be verified with isinstance at startup or in tests.
"""

from fsm.scheduling.ports.repositories import (
    AppointmentRepository,
    ServiceCallAttachmentRepository,
    ServiceCallRepository,
)
from fsm.scheduling.ports.calendar import CalendarPort
from fsm.scheduling.ports.notifications import NotificationPort
from fsm.scheduling.ports.unit_of_work import UnitOfWork
from fsm.scheduling.ports.outbox import OutboxEntry, OutboxOperation, OutboxRepository

__all__ = [
    "ServiceCallRepository",
    "AppointmentRepository",
    "ServiceCallAttachmentRepository",
    "CalendarPort",
    "NotificationPort",
    "UnitOfWork",
    "OutboxEntry",
    "OutboxOperation",
    "OutboxRepository",
]
