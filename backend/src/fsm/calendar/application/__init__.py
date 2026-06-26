"""Calendar bounded context — application layer.

Re-exports the CalendarConnectionService for use by the composition root.
"""
from fsm.calendar.application.connection_service import CalendarConnectionService

__all__ = ["CalendarConnectionService"]
