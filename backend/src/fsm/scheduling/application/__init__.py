"""Application layer for the scheduling bounded context.

Orchestrates domain operations against the port interfaces, keeping
infrastructure adapters out of business logic. Three services are provided:

- ServiceCallService: creates and manages the service call lifecycle
- AppointmentService: handles slot proposals, booking, rescheduling,
  cancellation, and detail updates; enqueues outbox entries instead of calling
  the calendar synchronously
- CalendarProjectionDispatcher: reads pending outbox entries and projects them
  to the external calendar via CalendarPort
"""

from fsm.scheduling.application.service_call_service import ServiceCallService
from fsm.scheduling.application.appointment_service import AppointmentService
from fsm.scheduling.application.calendar_projection_dispatcher import CalendarProjectionDispatcher

__all__ = [
    "ServiceCallService",
    "AppointmentService",
    "CalendarProjectionDispatcher",
]
