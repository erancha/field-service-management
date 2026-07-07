"""Tests for availability slot generation in the scheduling domain."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo


from fsm.scheduling.domain import TimeRange, WeeklyWorkingHours
from fsm.scheduling.domain.availability import generate_slots, is_available

UTC = ZoneInfo("UTC")
JERUSALEM = ZoneInfo("Asia/Jerusalem")


def _dt(d: date, hour: int, minute: int = 0) -> "datetime":
    from datetime import datetime
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=UTC)


# A Sunday (Sun=6 in Python weekday) that is a working day under default schedule
# 2024-01-07 is a Sunday
SUNDAY = date(2024, 1, 7)
# 2024-01-08 is a Monday (weekday=0)
MONDAY = date(2024, 1, 8)
# 2024-01-12 is a Friday (weekday=4) — non-working under default schedule
FRIDAY = date(2024, 1, 12)
# 2024-01-13 is a Saturday (weekday=5) — non-working under default schedule
SATURDAY = date(2024, 1, 13)


def test_full_working_day_no_busy_no_holiday():
    """09:00–17:00 with 60-min slots yields exactly 8 slots with correct boundaries."""
    wh = WeeklyWorkingHours.default()
    slots = generate_slots(
        working_hours=wh,
        start_date=SUNDAY,
        end_date=SUNDAY,
        busy=[],
        holidays=set(),
        slot_duration=timedelta(hours=1),
        tz=UTC,
    )
    assert len(slots) == 8
    assert slots[0].start == _dt(SUNDAY, 9)
    assert slots[0].end == _dt(SUNDAY, 10)
    assert slots[-1].start == _dt(SUNDAY, 16)
    assert slots[-1].end == _dt(SUNDAY, 17)


def test_holiday_yields_no_slots():
    """A date in holidays produces no slots."""
    wh = WeeklyWorkingHours.default()
    slots = generate_slots(
        working_hours=wh,
        start_date=SUNDAY,
        end_date=SUNDAY,
        busy=[],
        holidays={SUNDAY},
        slot_duration=timedelta(hours=1),
        tz=UTC,
    )
    assert slots == []


def test_non_working_weekday_yields_no_slots():
    """Friday and Saturday are not in the default Sun–Thu schedule."""
    wh = WeeklyWorkingHours.default()
    for non_working in (FRIDAY, SATURDAY):
        slots = generate_slots(
            working_hours=wh,
            start_date=non_working,
            end_date=non_working,
            busy=[],
            holidays=set(),
            slot_duration=timedelta(hours=1),
            tz=UTC,
        )
        assert slots == [], f"Expected no slots for {non_working}"


def test_busy_interval_removes_overlapping_slots():
    """A busy interval spanning 10:00–11:00 removes only that slot."""
    wh = WeeklyWorkingHours.default()
    busy_slot = TimeRange(
        start=_dt(SUNDAY, 10),
        end=_dt(SUNDAY, 11),
    )
    slots = generate_slots(
        working_hours=wh,
        start_date=SUNDAY,
        end_date=SUNDAY,
        busy=[busy_slot],
        holidays=set(),
        slot_duration=timedelta(hours=1),
        tz=UTC,
    )
    # 8 total - 1 blocked = 7
    assert len(slots) == 7
    starts = [s.start for s in slots]
    assert _dt(SUNDAY, 10) not in starts
    assert _dt(SUNDAY, 9) in starts
    assert _dt(SUNDAY, 11) in starts


def test_busy_touching_boundary_does_not_remove_adjacent_slot():
    """Busy interval [11:00, 12:00) does not remove slot [10:00, 11:00) — adjacent, no overlap."""
    wh = WeeklyWorkingHours.default()
    busy_slot = TimeRange(
        start=_dt(SUNDAY, 11),
        end=_dt(SUNDAY, 12),
    )
    slots = generate_slots(
        working_hours=wh,
        start_date=SUNDAY,
        end_date=SUNDAY,
        busy=[busy_slot],
        holidays=set(),
        slot_duration=timedelta(hours=1),
        tz=UTC,
    )
    # 8 total - 1 blocked = 7; slot [10:00, 11:00) must survive
    assert len(slots) == 7
    starts = [s.start for s in slots]
    assert _dt(SUNDAY, 10) in starts
    assert _dt(SUNDAY, 11) not in starts


def test_partial_trailing_slot_excluded():
    """A 2.5h window with 60-min slots yields exactly 2 slots (trailing 30 min excluded)."""
    from datetime import time
    from fsm.scheduling.domain.working_hours import DailyHours

    # Build custom working hours: Sunday 09:00–11:30
    wh = WeeklyWorkingHours(
        windows=[DailyHours(weekday=SUNDAY.weekday(), start=time(9, 0), end=time(11, 30))]
    )
    slots = generate_slots(
        working_hours=wh,
        start_date=SUNDAY,
        end_date=SUNDAY,
        busy=[],
        holidays=set(),
        slot_duration=timedelta(hours=1),
        tz=UTC,
    )
    assert len(slots) == 2
    assert slots[0].start == _dt(SUNDAY, 9)
    assert slots[0].end == _dt(SUNDAY, 10)
    assert slots[1].start == _dt(SUNDAY, 10)
    assert slots[1].end == _dt(SUNDAY, 11)


def test_multi_day_range_aggregates_and_sorts():
    """A Sun–Mon range returns Sunday slots followed by Monday slots, sorted by start."""
    wh = WeeklyWorkingHours.default()
    slots = generate_slots(
        working_hours=wh,
        start_date=SUNDAY,
        end_date=MONDAY,
        busy=[],
        holidays=set(),
        slot_duration=timedelta(hours=1),
        tz=UTC,
    )
    assert len(slots) == 16  # 8 Sunday + 8 Monday
    # First slot is Sunday 09:00
    assert slots[0].start == _dt(SUNDAY, 9)
    # 9th slot is Monday 09:00
    assert slots[8].start == _dt(MONDAY, 9)
    # Verify sorted order
    assert slots == sorted(slots, key=lambda s: s.start)


def test_slot_duration_not_dividing_window_evenly():
    """90-min slots in an 8h window: floor(480/90)=5 slots, 30 min remainder excluded."""
    wh = WeeklyWorkingHours.default()  # 09:00–17:00 = 480 min
    slots = generate_slots(
        working_hours=wh,
        start_date=SUNDAY,
        end_date=SUNDAY,
        busy=[],
        holidays=set(),
        slot_duration=timedelta(minutes=90),
        tz=UTC,
    )
    assert len(slots) == 5
    assert slots[0].start == _dt(SUNDAY, 9, 0)
    assert slots[0].end == _dt(SUNDAY, 10, 30)
    assert slots[4].start == _dt(SUNDAY, 15, 0)
    assert slots[4].end == _dt(SUNDAY, 16, 30)


# ---------------------------------------------------------------------------
# DST-correctness tests (Asia/Jerusalem)
# ---------------------------------------------------------------------------

# 2024-10-27: Israel falls back from UTC+3 to UTC+2 at 02:00 wall-clock.
# A 09:00–17:00 window is entirely post-transition, so all boundaries carry +02:00.
_DST_FALLBACK_DATE = date(2024, 10, 27)
# Weekday: 2024-10-27 is a Sunday (weekday=6), which is a working day in the default schedule.
_OFFSET_POST = timezone(timedelta(hours=2))   # +02:00 (post-transition, IDT → IST)


def test_dst_fallback_day_yields_correct_slot_count():
    """09:00–17:00 on the DST fall-back day yields exactly 8 one-hour wall-clock slots."""
    wh = WeeklyWorkingHours.default()
    slots = generate_slots(
        working_hours=wh,
        start_date=_DST_FALLBACK_DATE,
        end_date=_DST_FALLBACK_DATE,
        busy=[],
        holidays=set(),
        slot_duration=timedelta(hours=1),
        tz=JERUSALEM,
    )
    assert len(slots) == 8


def test_dst_fallback_day_slot_boundaries_carry_correct_offset():
    """Each slot boundary on the fall-back day carries +02:00 (post-transition IST)."""
    wh = WeeklyWorkingHours.default()
    slots = generate_slots(
        working_hours=wh,
        start_date=_DST_FALLBACK_DATE,
        end_date=_DST_FALLBACK_DATE,
        busy=[],
        holidays=set(),
        slot_duration=timedelta(hours=1),
        tz=JERUSALEM,
    )
    for slot in slots:
        assert slot.start.utcoffset() == timedelta(hours=2), (
            f"Expected +02:00 on start {slot.start!r}"
        )
        assert slot.end.utcoffset() == timedelta(hours=2), (
            f"Expected +02:00 on end {slot.end!r}"
        )


def test_dst_fallback_day_slots_are_one_hour_wall_clock_apart():
    """Adjacent slot boundaries differ by exactly 1 wall-clock hour."""
    wh = WeeklyWorkingHours.default()
    slots = generate_slots(
        working_hours=wh,
        start_date=_DST_FALLBACK_DATE,
        end_date=_DST_FALLBACK_DATE,
        busy=[],
        holidays=set(),
        slot_duration=timedelta(hours=1),
        tz=JERUSALEM,
    )
    for slot in slots:
        wall_start_hour = slot.start.hour
        wall_end_hour = slot.end.hour
        assert wall_end_hour - wall_start_hour == 1, (
            f"Expected 1-hour wall-clock gap; got start={slot.start!r}, end={slot.end!r}"
        )


def test_normal_day_jerusalem_slot_count_unaffected():
    """On a non-DST Thursday (2024-10-24), Jerusalem yields 8 one-hour slots."""
    normal_thursday = date(2024, 10, 24)  # weekday=3, working day
    wh = WeeklyWorkingHours.default()
    slots = generate_slots(
        working_hours=wh,
        start_date=normal_thursday,
        end_date=normal_thursday,
        busy=[],
        holidays=set(),
        slot_duration=timedelta(hours=1),
        tz=JERUSALEM,
    )
    assert len(slots) == 8


# ---------------------------------------------------------------------------
# Two-pointer sweep optimisation tests
# ---------------------------------------------------------------------------

def test_many_busy_intervals_sweep_matches_naive_filter():
    """Sweep result matches a naive O(n·m) reference over a multi-day range with many busy intervals."""
    wh = WeeklyWorkingHours.default()
    # Sun 2024-01-07 through Thu 2024-01-11 — 5 working days × 8 slots = 40 total slots.
    start = date(2024, 1, 7)
    end = date(2024, 1, 11)

    # Scatter busy intervals: one per hour across several days, leaving gaps.
    busy = [
        TimeRange(start=_dt(date(2024, 1, 7), h), end=_dt(date(2024, 1, 7), h + 1))
        for h in range(9, 15)  # block 9–15 on Sunday (6 slots)
    ] + [
        TimeRange(start=_dt(date(2024, 1, 8), h), end=_dt(date(2024, 1, 8), h + 1))
        for h in range(11, 17)  # block 11–17 on Monday (6 slots)
    ] + [
        TimeRange(start=_dt(date(2024, 1, 9), h), end=_dt(date(2024, 1, 9), h + 1))
        for h in range(9, 17)  # block entire Tuesday (8 slots)
    ]

    result = generate_slots(
        working_hours=wh,
        start_date=start,
        end_date=end,
        busy=busy,
        holidays=set(),
        slot_duration=timedelta(hours=1),
        tz=UTC,
    )

    # Compute expected with a simple inline O(n·m) reference.
    all_slots: list[TimeRange] = []
    current = start
    while current <= end:
        daily = wh.window_for(current.weekday())
        if daily is not None:
            from datetime import datetime as _datetime
            s = _datetime(current.year, current.month, current.day, daily.start.hour, daily.start.minute)
            duration = timedelta(hours=1)
            e_limit = _datetime(current.year, current.month, current.day, daily.end.hour, daily.end.minute)
            while s + duration <= e_limit:
                all_slots.append(TimeRange(start=s.replace(tzinfo=UTC), end=(s + duration).replace(tzinfo=UTC)))
                s += duration
        current += timedelta(days=1)
    expected = [sl for sl in all_slots if not any(sl.overlaps(b) for b in busy)]

    assert result == expected


def test_long_busy_interval_spans_multiple_slots():
    """A single busy interval covering several consecutive slots blocks all of them, free slots after are retained."""
    wh = WeeklyWorkingHours.default()
    # Busy from 10:00 to 14:00 blocks slots [10,11), [11,12), [12,13), [13,14).
    long_busy = TimeRange(start=_dt(SUNDAY, 10), end=_dt(SUNDAY, 14))
    slots = generate_slots(
        working_hours=wh,
        start_date=SUNDAY,
        end_date=SUNDAY,
        busy=[long_busy],
        holidays=set(),
        slot_duration=timedelta(hours=1),
        tz=UTC,
    )
    # 8 total - 4 blocked = 4 free: [9,10), [14,15), [15,16), [16,17)
    assert len(slots) == 4
    starts = {s.start for s in slots}
    assert _dt(SUNDAY, 9) in starts
    assert _dt(SUNDAY, 10) not in starts
    assert _dt(SUNDAY, 11) not in starts
    assert _dt(SUNDAY, 12) not in starts
    assert _dt(SUNDAY, 13) not in starts
    assert _dt(SUNDAY, 14) in starts
    assert _dt(SUNDAY, 15) in starts
    assert _dt(SUNDAY, 16) in starts


def test_unsorted_busy_intervals_produce_correct_result():
    """Busy intervals passed in reverse order are sorted internally; result matches sorted input."""
    wh = WeeklyWorkingHours.default()
    busy_sorted = [
        TimeRange(start=_dt(SUNDAY, 10), end=_dt(SUNDAY, 11)),
        TimeRange(start=_dt(SUNDAY, 13), end=_dt(SUNDAY, 14)),
        TimeRange(start=_dt(SUNDAY, 15), end=_dt(SUNDAY, 16)),
    ]
    busy_reversed = list(reversed(busy_sorted))

    slots_sorted = generate_slots(
        working_hours=wh,
        start_date=SUNDAY,
        end_date=SUNDAY,
        busy=busy_sorted,
        holidays=set(),
        slot_duration=timedelta(hours=1),
        tz=UTC,
    )
    slots_reversed = generate_slots(
        working_hours=wh,
        start_date=SUNDAY,
        end_date=SUNDAY,
        busy=busy_reversed,
        holidays=set(),
        slot_duration=timedelta(hours=1),
        tz=UTC,
    )
    assert slots_sorted == slots_reversed
    # 8 total - 3 blocked = 5 free
    assert len(slots_sorted) == 5


class TestIsAvailable:
    """is_available accepts a range iff it fits working hours on a non-excluded local day."""

    _TZ_UTC = timezone.utc
    # Monday 2024-06-10; WeeklyWorkingHours.default() works Sun-Thu 09:00-17:00.
    _MONDAY = date(2024, 6, 10)

    def _range(self, start_h, start_m, end_h, end_m, tz=None):
        tz = tz or self._TZ_UTC
        d = self._MONDAY
        return TimeRange(
            start=datetime(d.year, d.month, d.day, start_h, start_m, tzinfo=tz),
            end=datetime(d.year, d.month, d.day, end_h, end_m, tzinfo=tz),
        )

    def test_inside_working_hours_passes(self):
        assert is_available(
            working_hours=WeeklyWorkingHours.default(),
            tz=self._TZ_UTC,
            excluded_dates=frozenset(),
            time_range=self._range(9, 0, 11, 0),
        )

    def test_range_ending_exactly_at_window_end_passes(self):
        assert is_available(
            working_hours=WeeklyWorkingHours.default(),
            tz=self._TZ_UTC,
            excluded_dates=frozenset(),
            time_range=self._range(15, 0, 17, 0),
        )

    def test_range_starting_before_window_fails(self):
        assert not is_available(
            working_hours=WeeklyWorkingHours.default(),
            tz=self._TZ_UTC,
            excluded_dates=frozenset(),
            time_range=self._range(8, 30, 10, 0),
        )

    def test_range_ending_after_window_fails(self):
        assert not is_available(
            working_hours=WeeklyWorkingHours.default(),
            tz=self._TZ_UTC,
            excluded_dates=frozenset(),
            time_range=self._range(16, 0, 17, 30),
        )

    def test_non_working_weekday_fails(self):
        # 2024-06-14 is a Friday — not in the default Sun-Thu schedule.
        friday = TimeRange(
            start=datetime(2024, 6, 14, 10, 0, tzinfo=self._TZ_UTC),
            end=datetime(2024, 6, 14, 11, 0, tzinfo=self._TZ_UTC),
        )
        assert not is_available(
            working_hours=WeeklyWorkingHours.default(),
            tz=self._TZ_UTC,
            excluded_dates=frozenset(),
            time_range=friday,
        )

    def test_excluded_date_fails(self):
        assert not is_available(
            working_hours=WeeklyWorkingHours.default(),
            tz=self._TZ_UTC,
            excluded_dates=frozenset({self._MONDAY}),
            time_range=self._range(9, 0, 11, 0),
        )

    def test_range_spanning_local_days_fails(self):
        overnight = TimeRange(
            start=datetime(2024, 6, 10, 16, 0, tzinfo=self._TZ_UTC),
            end=datetime(2024, 6, 11, 10, 0, tzinfo=self._TZ_UTC),
        )
        assert not is_available(
            working_hours=WeeklyWorkingHours.default(),
            tz=self._TZ_UTC,
            excluded_dates=frozenset(),
            time_range=overnight,
        )

    def test_localization_governs_the_window(self):
        # 06:30-08:30 UTC is 09:30-11:30 at UTC+3 — inside the local window even
        # though the UTC wall clock is before opening.
        tz_plus3 = timezone(timedelta(hours=3))
        rng = TimeRange(
            start=datetime(2024, 6, 10, 6, 30, tzinfo=timezone.utc),
            end=datetime(2024, 6, 10, 8, 30, tzinfo=timezone.utc),
        )
        assert is_available(
            working_hours=WeeklyWorkingHours.default(),
            tz=tz_plus3,
            excluded_dates=frozenset(),
            time_range=rng,
        )
        # The same instants evaluated as UTC wall clock start at 06:30 — rejected.
        assert not is_available(
            working_hours=WeeklyWorkingHours.default(),
            tz=timezone.utc,
            excluded_dates=frozenset(),
            time_range=rng,
        )
