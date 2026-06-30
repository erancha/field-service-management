"""Domain exception hierarchy for the scheduling bounded context."""


class SchedulingError(Exception):
    """Base class for all scheduling domain errors."""


class InvalidTimeRange(SchedulingError):
    """Raised when a time range is logically invalid (e.g. start >= end)."""


class InvalidTransition(SchedulingError):
    """Raised when a lifecycle transition is not permitted from the current state."""


class NotFoundError(SchedulingError):
    """Raised when a repository lookup finds no entity matching the requested id."""


class SlotUnavailable(SchedulingError):
    """Raised when a requested time slot overlaps an existing active appointment."""
