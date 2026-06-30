"""Pure domain layer for the scheduling bounded context.

Defines the core types, entities, value objects, and lifecycle rules for
service calls and appointments. This layer has no I/O, no persistence, and
no dependency outside the Python standard library.

Public types re-exported here:
- TimeRange: half-open [start, end) interval for scheduling windows
- DailyHours, WeeklyWorkingHours: technician availability model
- ServiceCallStatus, ServiceCall: customer request lifecycle
- AppointmentStatus, Appointment: scheduled visit lifecycle
- SchedulingError, InvalidTimeRange, InvalidTransition, NotFoundError,
  SlotUnavailable: error hierarchy
- generate_slots: deterministic slot generation for technician availability
"""

from fsm.scheduling.domain.errors import (
    InvalidTimeRange,
    InvalidTransition,
    NotFoundError,
    SchedulingError,
    SlotUnavailable,
)
from fsm.scheduling.domain.time_range import TimeRange
from fsm.scheduling.domain.working_hours import DailyHours, WeeklyWorkingHours
from fsm.scheduling.domain.service_call import ServiceCall, ServiceCallStatus
from fsm.scheduling.domain.appointment import Appointment, AppointmentStatus
from fsm.scheduling.domain.availability import generate_slots

__all__ = [
    "SchedulingError",
    "InvalidTimeRange",
    "InvalidTransition",
    "NotFoundError",
    "SlotUnavailable",
    "TimeRange",
    "DailyHours",
    "WeeklyWorkingHours",
    "ServiceCall",
    "ServiceCallStatus",
    "Appointment",
    "AppointmentStatus",
    "generate_slots",
]
