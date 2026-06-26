"""Outbound port protocols for the scheduling bounded context.

Ports define the boundary between the domain and its infrastructure adapters.
All protocols are @runtime_checkable so adapters can be verified with isinstance
at startup or in tests.

Re-exported protocols:
- ServiceCallRepository: add, get, save
- AppointmentRepository: add, get, save, list_for_technician_between
- CalendarPort: get_busy, create_event, update_event, delete_event
- NotificationPort: appointment_booked, appointment_rescheduled, appointment_cancelled
- UnitOfWork: context-manager owning one transaction; exposes service_calls + appointments + outbox
- OutboxOperation, OutboxEntry, OutboxRepository: transactional outbox for calendar projection
"""

from fsm.scheduling.ports.repositories import AppointmentRepository, ServiceCallRepository
from fsm.scheduling.ports.calendar import CalendarPort
from fsm.scheduling.ports.notifications import NotificationPort
from fsm.scheduling.ports.unit_of_work import UnitOfWork
from fsm.scheduling.ports.outbox import OutboxEntry, OutboxOperation, OutboxRepository

__all__ = [
    "ServiceCallRepository",
    "AppointmentRepository",
    "CalendarPort",
    "NotificationPort",
    "UnitOfWork",
    "OutboxEntry",
    "OutboxOperation",
    "OutboxRepository",
]
