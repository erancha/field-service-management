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


class IncompleteContactInfo(SchedulingError):
    """Raised when a booking lacks the contact data an appointment requires.

    missing names each absent party/field (e.g. "customer phone", "technician phone") so a
    caller can report which data must be collected before the booking can proceed.
    """

    def __init__(self, missing: list[str]) -> None:
        self.missing = list(missing)
        super().__init__("Missing required contact information: " + ", ".join(missing))
