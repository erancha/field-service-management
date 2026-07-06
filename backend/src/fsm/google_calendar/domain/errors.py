"""Domain exception hierarchy for the calendar bounded context."""


class CalendarError(Exception):
    """Base class for all calendar domain errors."""


class NotFoundError(CalendarError):
    """Raised when a repository lookup finds no entity matching the requested id."""


class DuplicateTechnicianError(CalendarError):
    """Raised when a second calendar connection is created for the same technician."""
