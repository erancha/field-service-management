"""Tests for TimeRange value object."""
from datetime import datetime, timezone, timedelta
import pytest

from fsm.scheduling.domain import TimeRange, InvalidTimeRange


def _dt(hour: int, minute: int = 0) -> datetime:
    return datetime(2024, 6, 10, hour, minute, tzinfo=timezone.utc)


class TestTimeRangeConstruction:
    def test_valid_range_creates_successfully(self):
        tr = TimeRange(start=_dt(9), end=_dt(10))
        assert tr.start == _dt(9)
        assert tr.end == _dt(10)

    def test_start_equal_to_end_raises(self):
        with pytest.raises(InvalidTimeRange):
            TimeRange(start=_dt(10), end=_dt(10))

    def test_start_after_end_raises(self):
        with pytest.raises(InvalidTimeRange):
            TimeRange(start=_dt(11), end=_dt(10))

    def test_is_frozen(self):
        tr = TimeRange(start=_dt(9), end=_dt(10))
        with pytest.raises((AttributeError, TypeError)):
            tr.start = _dt(8)  # type: ignore[misc]


class TestTimeRangeDuration:
    def test_duration_one_hour(self):
        tr = TimeRange(start=_dt(9), end=_dt(10))
        assert tr.duration == timedelta(hours=1)

    def test_duration_30_minutes(self):
        tr = TimeRange(start=_dt(9), end=_dt(9, 30))
        assert tr.duration == timedelta(minutes=30)


class TestTimeRangeOverlaps:
    def test_overlapping_ranges_return_true(self):
        a = TimeRange(start=_dt(9), end=_dt(11))
        b = TimeRange(start=_dt(10), end=_dt(12))
        assert a.overlaps(b) is True
        assert b.overlaps(a) is True

    def test_one_contained_in_other(self):
        outer = TimeRange(start=_dt(8), end=_dt(18))
        inner = TimeRange(start=_dt(10), end=_dt(12))
        assert outer.overlaps(inner) is True
        assert inner.overlaps(outer) is True

    def test_disjoint_ranges_return_false(self):
        a = TimeRange(start=_dt(9), end=_dt(10))
        b = TimeRange(start=_dt(11), end=_dt(12))
        assert a.overlaps(b) is False
        assert b.overlaps(a) is False

    def test_adjacent_ranges_do_not_overlap(self):
        # [9,10) and [10,11) touch but do NOT overlap under half-open semantics
        a = TimeRange(start=_dt(9), end=_dt(10))
        b = TimeRange(start=_dt(10), end=_dt(11))
        assert a.overlaps(b) is False
        assert b.overlaps(a) is False

    def test_same_range_overlaps_itself(self):
        a = TimeRange(start=_dt(9), end=_dt(10))
        assert a.overlaps(a) is True
