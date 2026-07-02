"""Tests for the iCalendar builder."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from fsm.scheduling.domain.appointment_context import AppointmentContext


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
        result = build_ics(appt, AppointmentContext())
        assert "BEGIN:VCALENDAR" in result
        assert "END:VCALENDAR" in result

    def test_contains_vevent(self):
        from fsm.notifications.adapters.ics import build_ics

        appt = _make_appointment(
            start=datetime(2025, 6, 10, 9, 0, tzinfo=timezone.utc),
            end=datetime(2025, 6, 10, 10, 0, tzinfo=timezone.utc),
        )
        result = build_ics(appt, AppointmentContext())
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
        result = build_ics(appt, AppointmentContext())
        assert f"UID:fsm-{appt_id}@fsm.local" in result

    def test_dtstart_dtend_in_utc_zulu(self):
        from fsm.notifications.adapters.ics import build_ics

        appt = _make_appointment(
            start=datetime(2025, 6, 10, 9, 0, tzinfo=timezone.utc),
            end=datetime(2025, 6, 10, 10, 0, tzinfo=timezone.utc),
        )
        result = build_ics(appt, AppointmentContext())
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
        assert build_ics(appt, AppointmentContext()) == build_ics(appt, AppointmentContext())


class TestBuildIcsContext:
    def _appt(self):
        return _make_appointment(
            start=datetime(2025, 6, 10, 9, 0, tzinfo=timezone.utc),
            end=datetime(2025, 6, 10, 10, 0, tzinfo=timezone.utc),
        )

    def test_summary_combines_name_and_problem(self):
        from fsm.notifications.adapters.ics import build_ics

        ctx = AppointmentContext(customer_name="Ada Lovelace", problem_description="No hot water")
        assert "SUMMARY:Ada Lovelace — No hot water" in build_ics(self._appt(), ctx)

    def test_summary_falls_back_to_generic_when_context_empty(self):
        from fsm.notifications.adapters.ics import build_ics

        assert "SUMMARY:Field service appointment" in build_ics(self._appt(), AppointmentContext())

    def test_description_carries_problem(self):
        from fsm.notifications.adapters.ics import build_ics

        ctx = AppointmentContext(problem_description="No hot water")
        assert "DESCRIPTION:No hot water" in build_ics(self._appt(), ctx)

    def test_no_description_line_when_problem_blank(self):
        from fsm.notifications.adapters.ics import build_ics

        assert "DESCRIPTION" not in build_ics(self._appt(), AppointmentContext(problem_description="  \n"))
        assert "DESCRIPTION" not in build_ics(self._appt(), AppointmentContext())

    def test_text_fields_are_escaped_per_rfc5545(self):
        from fsm.notifications.adapters.ics import build_ics

        ctx = AppointmentContext(problem_description="Leak; kitchen, floor\nback\\room")
        result = build_ics(self._appt(), ctx)
        assert "DESCRIPTION:Leak\\; kitchen\\, floor\\nback\\\\room" in result


class TestBuildIcsLineFolding:
    def _appt(self):
        return _make_appointment(
            start=datetime(2025, 6, 10, 9, 0, tzinfo=timezone.utc),
            end=datetime(2025, 6, 10, 10, 0, tzinfo=timezone.utc),
        )

    def test_no_physical_line_exceeds_75_octets(self):
        from fsm.notifications.adapters.ics import build_ics

        ctx = AppointmentContext(
            customer_name="A" * 100,
            problem_description="B" * 300,
        )
        result = build_ics(self._appt(), ctx)
        for line in result.split("\r\n"):
            assert len(line.encode("utf-8")) <= 75

    def test_folded_summary_round_trips_to_original_content_line(self):
        from fsm.notifications.adapters.ics import build_ics

        ctx = AppointmentContext(customer_name="C" * 200, problem_description="short")
        result = build_ics(self._appt(), ctx)
        lines = result.split("\r\n")
        start = next(i for i, line in enumerate(lines) if line.startswith("SUMMARY:"))
        folded = [lines[start]]
        i = start + 1
        while i < len(lines) and lines[i].startswith(" "):
            folded.append(lines[i][1:])
            i += 1
        assert "".join(folded) == f"SUMMARY:{ctx.summary_line()}"

    def test_multibyte_description_folds_on_valid_utf8_boundaries(self):
        from fsm.notifications.adapters.ics import build_ics

        ctx = AppointmentContext(problem_description="é—" * 100)
        result = build_ics(self._appt(), ctx)
        for chunk in result.encode("utf-8").split(b"\r\n"):
            chunk.decode("utf-8")


class TestBuildIcsLocationAndPhone:
    def _appt(self):
        return _make_appointment(
            start=datetime(2025, 6, 10, 9, 0, tzinfo=timezone.utc),
            end=datetime(2025, 6, 10, 10, 0, tzinfo=timezone.utc),
        )

    def test_location_line_present_and_escaped(self):
        from fsm.notifications.adapters.ics import build_ics

        ctx = AppointmentContext(service_address="12 Main St, Springfield")
        assert "LOCATION:12 Main St\\, Springfield" in build_ics(self._appt(), ctx)

    def test_no_location_line_when_address_blank(self):
        from fsm.notifications.adapters.ics import build_ics

        assert "LOCATION" not in build_ics(self._appt(), AppointmentContext(service_address=" "))
        assert "LOCATION" not in build_ics(self._appt(), AppointmentContext())

    def test_phone_joins_description(self):
        from fsm.notifications.adapters.ics import build_ics

        ctx = AppointmentContext(problem_description="No hot water", customer_phone="+972-50-123")
        assert "DESCRIPTION:No hot water\\nPhone: +972-50-123" in build_ics(self._appt(), ctx)

    def test_phone_alone_produces_description(self):
        from fsm.notifications.adapters.ics import build_ics

        ctx = AppointmentContext(customer_phone="+972-50-123")
        assert "DESCRIPTION:Phone: +972-50-123" in build_ics(self._appt(), ctx)

    def test_long_address_is_folded(self):
        from fsm.notifications.adapters.ics import build_ics

        ctx = AppointmentContext(service_address="Very long street name " * 10)
        for line in build_ics(self._appt(), ctx).split("\r\n"):
            assert len(line.encode("utf-8")) <= 75

    def test_folded_location_round_trips_to_escaped_content_line(self):
        from fsm.notifications.adapters.ics import _escape_text, build_ics

        address = "Building 7, Suite 12; c/o Warehouse \\ Depot, " + "Long Industrial Road, " * 3 + "end"
        ctx = AppointmentContext(service_address=address)
        lines = build_ics(self._appt(), ctx).split("\r\n")

        for line in lines:
            assert len(line.encode("utf-8")) <= 75

        start = next(i for i, line in enumerate(lines) if line.startswith("LOCATION:"))
        folded = [lines[start]]
        i = start + 1
        while i < len(lines) and lines[i].startswith(" "):
            folded.append(lines[i][1:])
            i += 1
        assert "".join(folded) == f"LOCATION:{_escape_text(address)}"
