"""Calendar bounded context — domain layer.

Exports the connection entity and its status enum, plus the domain error hierarchy.
"""
from fsm.calendar.domain.connection import CalendarConnection, CalendarConnectionStatus
from fsm.calendar.domain.errors import CalendarError, DuplicateTechnicianError, NotFoundError

__all__ = [
    "CalendarConnection",
    "CalendarConnectionStatus",
    "CalendarError",
    "DuplicateTechnicianError",
    "NotFoundError",
]
