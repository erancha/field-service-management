"""Domain exception hierarchy for the scheduling bounded context."""

from datetime import datetime


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


class BookingRateLimited(SchedulingError):
    """Raised when a customer's recent cancellations put their booking on a cool-off.

    retry_at is the moment booking reopens; the message renders it in retry_at's own
    timezone, so the raiser controls the zone the customer sees.
    """

    def __init__(self, retry_at: datetime) -> None:
        self.retry_at = retry_at
        super().__init__(
            "Too many recently cancelled appointments on this account; "
            f"booking reopens at {retry_at:%Y-%m-%d %H:%M %Z}."
        )
