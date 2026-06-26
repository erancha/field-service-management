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


class MissingCalendarEvent(SchedulingError):
    """Raised when an appointment has no external_event_id but a calendar operation requires one.

    Precondition: every appointment that has left the booking flow must carry a
    non-None external_event_id. This error signals a broken invariant — typically
    an appointment that was persisted without a completed calendar.create_event call.
    """
