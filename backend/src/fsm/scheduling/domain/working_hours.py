"""Technician weekly availability expressed as bookable daily windows.

Weekday numbering follows Python's date.weekday(): Mon=0, Tue=1, Wed=2,
Thu=3, Fri=4, Sat=5, Sun=6.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import time

from fsm.scheduling.domain.errors import InvalidTimeRange, SchedulingError

_MONDAY = 0
_TUESDAY = 1
_WEDNESDAY = 2
_THURSDAY = 3
_FRIDAY = 4
_SATURDAY = 5
_SUNDAY = 6

_DEFAULT_START = time(9, 0)
_DEFAULT_END = time(17, 0)
# Israeli work week: Sunday through Thursday
_DEFAULT_WORKDAYS = (_SUNDAY, _MONDAY, _TUESDAY, _WEDNESDAY, _THURSDAY)


@dataclass(frozen=True)
class DailyHours:
    """Immutable bookable window for a single weekday.

    weekday follows Python's date.weekday() convention (Mon=0 … Sun=6).
    start must be strictly before end.
    """

    weekday: int
    start: time
    end: time

    def __post_init__(self) -> None:
        if self.start >= self.end:
            raise InvalidTimeRange(
                f"DailyHours start must be before end; got start={self.start!r}, end={self.end!r}"
            )


@dataclass(frozen=True)
class WeeklyWorkingHours:
    """Immutable collection of per-weekday bookable windows for one technician.

    Days not represented in windows are treated as non-working.

    windows is stored as a tuple so the instance is hashable, consistent with
    the frozen=True contract. Duplicate weekdays are rejected at construction.
    """

    windows: tuple[DailyHours, ...]

    def __post_init__(self) -> None:
        # Coerce any sequence to tuple so the field is always hashable.
        object.__setattr__(self, "windows", tuple(self.windows))
        weekdays = [dh.weekday for dh in self.windows]
        if len(weekdays) != len(set(weekdays)):
            raise SchedulingError(
                "WeeklyWorkingHours cannot have duplicate weekdays"
            )

    def window_for(self, weekday: int) -> DailyHours | None:
        """Return the bookable window for weekday, or None if not a working day."""
        for dh in self.windows:
            if dh.weekday == weekday:
                return dh
        return None

    @classmethod
    def default(cls) -> WeeklyWorkingHours:
        """Return the standard Israeli work-week schedule: Sun–Thu 09:00–17:00."""
        windows = tuple(
            DailyHours(weekday=wd, start=_DEFAULT_START, end=_DEFAULT_END)
            for wd in _DEFAULT_WORKDAYS
        )
        return cls(windows=windows)
