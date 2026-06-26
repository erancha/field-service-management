"""Tests for WeeklyWorkingHours and DailyHours value objects."""
from datetime import time
import pytest

from fsm.scheduling.domain import DailyHours, WeeklyWorkingHours, InvalidTimeRange, SchedulingError


# Python weekday: Mon=0, Tue=1, Wed=2, Thu=3, Fri=4, Sat=5, Sun=6
MONDAY = 0
TUESDAY = 1
WEDNESDAY = 2
THURSDAY = 3
FRIDAY = 4
SATURDAY = 5
SUNDAY = 6


class TestDailyHours:
    def test_valid_daily_hours(self):
        dh = DailyHours(weekday=MONDAY, start=time(9, 0), end=time(17, 0))
        assert dh.weekday == MONDAY
        assert dh.start == time(9, 0)
        assert dh.end == time(17, 0)

    def test_start_equal_to_end_raises(self):
        with pytest.raises(InvalidTimeRange):
            DailyHours(weekday=MONDAY, start=time(9, 0), end=time(9, 0))

    def test_start_after_end_raises(self):
        with pytest.raises(InvalidTimeRange):
            DailyHours(weekday=MONDAY, start=time(17, 0), end=time(9, 0))

    def test_is_frozen(self):
        dh = DailyHours(weekday=MONDAY, start=time(9, 0), end=time(17, 0))
        with pytest.raises((AttributeError, TypeError)):
            dh.start = time(8, 0)  # type: ignore[misc]


class TestWeeklyWorkingHoursDefault:
    def setup_method(self):
        self.wwh = WeeklyWorkingHours.default()

    def test_sunday_is_workday(self):
        dh = self.wwh.window_for(SUNDAY)
        assert dh is not None
        assert dh.start == time(9, 0)
        assert dh.end == time(17, 0)

    def test_monday_is_workday(self):
        assert self.wwh.window_for(MONDAY) is not None

    def test_tuesday_is_workday(self):
        assert self.wwh.window_for(TUESDAY) is not None

    def test_wednesday_is_workday(self):
        assert self.wwh.window_for(WEDNESDAY) is not None

    def test_thursday_is_workday(self):
        assert self.wwh.window_for(THURSDAY) is not None

    def test_friday_returns_none(self):
        assert self.wwh.window_for(FRIDAY) is None

    def test_saturday_returns_none(self):
        assert self.wwh.window_for(SATURDAY) is None

    def test_all_workday_hours_are_9_to_17(self):
        for weekday in (SUNDAY, MONDAY, TUESDAY, WEDNESDAY, THURSDAY):
            dh = self.wwh.window_for(weekday)
            assert dh is not None
            assert dh.start == time(9, 0)
            assert dh.end == time(17, 0)


class TestWeeklyWorkingHoursCustom:
    def test_custom_schedule(self):
        windows = [
            DailyHours(weekday=MONDAY, start=time(8, 0), end=time(16, 0)),
            DailyHours(weekday=WEDNESDAY, start=time(10, 0), end=time(18, 0)),
        ]
        wwh = WeeklyWorkingHours(windows=windows)
        assert wwh.window_for(MONDAY) is not None
        assert wwh.window_for(MONDAY).start == time(8, 0)
        assert wwh.window_for(TUESDAY) is None
        assert wwh.window_for(WEDNESDAY) is not None


class TestWeeklyWorkingHoursHashable:
    def test_equal_instances_hash_equal(self):
        wh1 = WeeklyWorkingHours.default()
        wh2 = WeeklyWorkingHours.default()
        assert wh1 == wh2
        assert hash(wh1) == hash(wh2)

    def test_can_be_used_as_dict_key(self):
        wh = WeeklyWorkingHours.default()
        d = {wh: "value"}
        assert d[wh] == "value"

    def test_list_input_coerced_to_tuple(self):
        windows_list = [DailyHours(weekday=MONDAY, start=time(9, 0), end=time(17, 0))]
        wh = WeeklyWorkingHours(windows=windows_list)
        assert isinstance(wh.windows, tuple)


class TestWeeklyWorkingHoursDuplicateWeekdays:
    def test_duplicate_weekday_raises_scheduling_error(self):
        """Constructing with two windows for the same weekday raises SchedulingError."""
        windows = [
            DailyHours(weekday=MONDAY, start=time(8, 0), end=time(12, 0)),
            DailyHours(weekday=MONDAY, start=time(13, 0), end=time(17, 0)),
        ]
        with pytest.raises(SchedulingError):
            WeeklyWorkingHours(windows=windows)

    def test_default_factory_has_no_duplicates(self):
        """Ensure default factory constructs without raising."""
        wh = WeeklyWorkingHours.default()
        assert wh is not None
        # All 5 workdays should be present without error
        assert len(wh.windows) == 5
