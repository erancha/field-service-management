"""Deterministic slot generation for technician availability.

Produces a list of free TimeRange slots for a given calendar range by carving
each working day's window into equal-duration intervals, then subtracting any
busy periods and holiday exclusions.

DST policy: slots are wall-clock-correct. Slot boundaries are computed on naive
datetimes and each boundary is localized independently with replace(tzinfo=tz),
so the count and labels reflect wall-clock time rather than absolute-time
arithmetic. Working windows are assumed not to span the DST transition hour
(the system's Sun–Thu 09:00–17:00 windows never do). Behaviour for windows
that cross the transition hour is defined (wall-clock arithmetic produces a
deterministic answer) but may not reflect real duration.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from typing import Container, Iterable

from fsm.scheduling.domain.time_range import TimeRange
from fsm.scheduling.domain.working_hours import WeeklyWorkingHours


def generate_slots(
    *,
    working_hours: WeeklyWorkingHours,
    start_date: date,
    end_date: date,
    busy: Iterable[TimeRange],
    holidays: Container[date],
    slot_duration: timedelta,
    tz: tzinfo,
) -> list[TimeRange]:
    """Return all free slots across [start_date, end_date] inclusive.

    Each working day is carved into consecutive slots of exactly slot_duration
    from the window start. Trailing partial slots are excluded. Any slot that
    overlaps an interval in busy is excluded.

    Slot boundaries are wall-clock-correct across DST transitions: each naive
    boundary datetime is localized independently so that a 09:00–17:00 window
    on a fall-back day yields exactly 8 one-hour slots with the correct
    post-transition UTC offset on every boundary.
    """
    # Sort once by start so the two-pointer sweep can advance monotonically.
    busy_list = sorted(busy, key=lambda b: b.start)
    slots: list[TimeRange] = []

    # left_ptr tracks the first busy interval that might overlap the current or
    # future slots. Intervals whose end <= slot.start can never overlap any later
    # slot (slots are generated in chronological order), so the pointer only
    # moves forward.
    left_ptr = 0
    current = start_date
    one_day = timedelta(days=1)

    while current <= end_date:
        if current not in holidays:
            daily = working_hours.window_for(current.weekday())
            if daily is not None:
                naive_window_start = datetime(
                    current.year, current.month, current.day,
                    daily.start.hour, daily.start.minute,
                )
                naive_window_end = datetime(
                    current.year, current.month, current.day,
                    daily.end.hour, daily.end.minute,
                )
                naive_s = naive_window_start
                while naive_s + slot_duration <= naive_window_end:
                    naive_e = naive_s + slot_duration
                    slot = TimeRange(
                        start=naive_s.replace(tzinfo=tz),
                        end=naive_e.replace(tzinfo=tz),
                    )

                    # Advance left_ptr past busy intervals that end at or before
                    # slot.start — they cannot overlap this slot or any later one.
                    while left_ptr < len(busy_list) and busy_list[left_ptr].end <= slot.start:
                        left_ptr += 1

                    # Scan forward from left_ptr while busy[i].start < slot.end;
                    # any interval starting at or after slot.end cannot overlap.
                    # A long busy interval straddling many slots stays at left_ptr
                    # until its own end passes slot.start, so it is never skipped.
                    free = True
                    i = left_ptr
                    while i < len(busy_list) and busy_list[i].start < slot.end:
                        if slot.overlaps(busy_list[i]):
                            free = False
                            break
                        i += 1

                    if free:
                        slots.append(slot)
                    naive_s = naive_e

        current += one_day

    return slots


@dataclass(frozen=True)
class AvailabilityInputs:
    """One technician's booking-policy inputs for validating a proposed time.

    excluded_dates carries both holidays and the technician's days off, already merged;
    the predicate treats them identically.
    """

    working_hours: WeeklyWorkingHours
    tz: tzinfo
    excluded_dates: frozenset[date]


def is_available(
    *,
    working_hours: WeeklyWorkingHours,
    tz: tzinfo,
    excluded_dates: Container[date],
    time_range: TimeRange,
) -> bool:
    """Return True iff time_range fits the booking policy on its local day.

    The range must fall on a single local (tz) day that is a working day and not
    excluded, and lie entirely within that day's working window. Ranges spanning
    local midnight are rejected — no working window crosses midnight.
    """
    local_start = time_range.start.astimezone(tz)
    local_end = time_range.end.astimezone(tz)
    if local_start.date() != local_end.date():
        return False
    day = local_start.date()
    if day in excluded_dates:
        return False
    window = working_hours.window_for(day.weekday())
    if window is None:
        return False
    return window.start <= local_start.time() and local_end.time() <= window.end
