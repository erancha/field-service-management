"""Pure domain layer for the scheduling bounded context.

Defines the core types, entities, value objects, and lifecycle rules for
service calls and appointments. This layer has no I/O, no persistence, and
no dependency outside the Python standard library.

Public types re-exported here:
- TimeRange: half-open [start, end) interval for scheduling windows
- DailyHours, WeeklyWorkingHours: technician availability model
- ServiceCallStatus, ServiceCall: customer request lifecycle
- AppointmentStatus, Appointment: scheduled visit lifecycle
- ServiceCallAttachment: a triage photo carried over onto a service call
- ContactInfo: per-party contact details a booking depends on
- CancellationRateLimit: cap on a customer's book/cancel churn
- SchedulingError, InvalidTimeRange, InvalidTransition, NotFoundError,
  SlotUnavailable, IncompleteContactInfo, BookingRateLimited: error hierarchy
- generate_slots: deterministic slot generation for technician availability
- build_ical_uid, parse_ical_uid: identity scheme tying appointments to calendar events
"""

from fsm.scheduling.domain.errors import (
    BookingRateLimited,
    IncompleteContactInfo,
    InvalidTimeRange,
    InvalidTransition,
    NotFoundError,
    SchedulingError,
    SlotUnavailable,
)
from fsm.scheduling.domain.booking_rate_limit import CancellationRateLimit
from fsm.scheduling.domain.contact_info import ContactInfo
from fsm.scheduling.domain.time_range import TimeRange
from fsm.scheduling.domain.working_hours import DailyHours, WeeklyWorkingHours
from fsm.scheduling.domain.service_call import ServiceCall, ServiceCallStatus
from fsm.scheduling.domain.appointment import Appointment, AppointmentStatus
from fsm.scheduling.domain.attachment import ServiceCallAttachment
from fsm.scheduling.domain.availability import generate_slots
from fsm.scheduling.domain.calendar_identity import build_ical_uid, parse_ical_uid

__all__ = [
    "SchedulingError",
    "InvalidTimeRange",
    "InvalidTransition",
    "NotFoundError",
    "SlotUnavailable",
    "IncompleteContactInfo",
    "BookingRateLimited",
    "CancellationRateLimit",
    "ContactInfo",
    "TimeRange",
    "DailyHours",
    "WeeklyWorkingHours",
    "ServiceCall",
    "ServiceCallStatus",
    "Appointment",
    "AppointmentStatus",
    "ServiceCallAttachment",
    "generate_slots",
    "build_ical_uid",
    "parse_ical_uid",
]
