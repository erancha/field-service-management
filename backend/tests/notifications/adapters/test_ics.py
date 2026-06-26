"""Tests for the iCalendar builder."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class _FakeTimeRange:
    start: datetime
    end: datetime


@dataclass
class _FakeAppointment:
    id: uuid.UUID
    time_range: _FakeTimeRange


def _make_appointment(
    start: datetime,
    end: datetime,
    appt_id: uuid.UUID | None = None,
) -> _FakeAppointment:
    return _FakeAppointment(
        id=appt_id or uuid.uuid4(),
        time_range=_FakeTimeRange(start=start, end=end),
    )


class TestBuildIcs:
    def test_contains_vcalendar_markers(self):
        from fsm.notifications.adapters.ics import build_ics

        appt = _make_appointment(
            start=datetime(2025, 6, 10, 9, 0, tzinfo=timezone.utc),
            end=datetime(2025, 6, 10, 10, 0, tzinfo=timezone.utc),
        )
        result = build_ics(appt)
        assert "BEGIN:VCALENDAR" in result
        assert "END:VCALENDAR" in result

    def test_contains_vevent(self):
        from fsm.notifications.adapters.ics import build_ics

        appt = _make_appointment(
            start=datetime(2025, 6, 10, 9, 0, tzinfo=timezone.utc),
            end=datetime(2025, 6, 10, 10, 0, tzinfo=timezone.utc),
        )
        result = build_ics(appt)
        assert "BEGIN:VEVENT" in result
        assert "END:VEVENT" in result

    def test_deterministic_uid(self):
        from fsm.notifications.adapters.ics import build_ics

        appt_id = uuid.uuid4()
        appt = _make_appointment(
            start=datetime(2025, 6, 10, 9, 0, tzinfo=timezone.utc),
            end=datetime(2025, 6, 10, 10, 0, tzinfo=timezone.utc),
            appt_id=appt_id,
        )
        result = build_ics(appt)
        assert f"UID:fsm-{appt_id}@fsm.local" in result

    def test_dtstart_dtend_in_utc_zulu(self):
        from fsm.notifications.adapters.ics import build_ics

        appt = _make_appointment(
            start=datetime(2025, 6, 10, 9, 0, tzinfo=timezone.utc),
            end=datetime(2025, 6, 10, 10, 0, tzinfo=timezone.utc),
        )
        result = build_ics(appt)
        assert "DTSTART:20250610T090000Z" in result
        assert "DTEND:20250610T100000Z" in result

    def test_is_deterministic_for_same_input(self):
        from fsm.notifications.adapters.ics import build_ics

        appt_id = uuid.uuid4()
        appt = _make_appointment(
            start=datetime(2025, 6, 10, 9, 0, tzinfo=timezone.utc),
            end=datetime(2025, 6, 10, 10, 0, tzinfo=timezone.utc),
            appt_id=appt_id,
        )
        assert build_ics(appt) == build_ics(appt)
