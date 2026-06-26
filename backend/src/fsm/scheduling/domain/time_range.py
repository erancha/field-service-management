"""Half-open time interval [start, end) for scheduling windows and appointments.

Both start and end must be timezone-aware datetimes. Naive datetimes are not
supported; callers are responsible for attaching timezone information before
constructing a TimeRange.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from fsm.scheduling.domain.errors import InvalidTimeRange


@dataclass(frozen=True)
class TimeRange:
    """Immutable half-open interval [start, end).

    Represents a contiguous window of time with clear open/close semantics:
    a point exactly at `end` is outside the range, so adjacent ranges share no
    overlap.
    """

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.start >= self.end:
            raise InvalidTimeRange(
                f"start must be strictly before end; got start={self.start!r}, end={self.end!r}"
            )

    @property
    def duration(self) -> timedelta:
        return self.end - self.start

    def overlaps(self, other: TimeRange) -> bool:
        """Return True iff this range and other share at least one point in time.

        Adjacent ranges (where one ends exactly where the other begins) do NOT
        overlap under half-open [start, end) semantics.
        """
        return self.start < other.end and other.start < self.end
