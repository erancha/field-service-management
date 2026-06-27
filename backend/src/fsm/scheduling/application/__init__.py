"""Application layer for the scheduling bounded context.

Orchestrates domain operations against the port interfaces, keeping
infrastructure adapters out of business logic. Booking use cases enqueue calendar
work through the transactional outbox rather than calling the calendar
synchronously; a separate dispatcher drains the outbox and projects to the
external calendar, and inbound reconciliation merges technician-side edits back
under database authority.
"""

from fsm.scheduling.application.service_call_service import ServiceCallService
from fsm.scheduling.application.appointment_service import AppointmentService
from fsm.scheduling.application.calendar_projection_dispatcher import CalendarProjectionDispatcher

__all__ = [
    "ServiceCallService",
    "AppointmentService",
    "CalendarProjectionDispatcher",
]
