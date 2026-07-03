"""Tests for the iCalendar builder."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fsm.scheduling.domain.appointment_context import AppointmentContext


@dataclass
class _FakeTimeRange:
    start: datetime
    end: datetime


@dataclass
class _FakeAppointment:
    id: uuid.UUID
    time_range: _FakeTimeRange
    created_at: datetime = datetime(2025, 6, 1, tzinfo=timezone.utc)
    updated_at: datetime = datetime(2025, 6, 1, tzinfo=timezone.utc)
    details: str | None = None


def _make_appointment(
    start: datetime,
    end: datetime,
    appt_id: uuid.UUID | None = None,
    details: str | None = None,
) -> _FakeAppointment:
    return _FakeAppointment(
        id=appt_id or uuid.uuid4(),
        time_range=_FakeTimeRange(start=start, end=end),
        details=details,
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

    def test_details_join_description_between_problem_and_phone(self):
        from fsm.notifications.adapters.ics import build_ics

        appt = _make_appointment(
            start=datetime(2025, 6, 10, 9, 0, tzinfo=timezone.utc),
            end=datetime(2025, 6, 10, 10, 0, tzinfo=timezone.utc),
            details="Gate code 4321",
        )
        ctx = AppointmentContext(problem_description="No hot water", customer_phone="+972-50-123")
        assert (
            "DESCRIPTION:No hot water\\nGate code 4321\\nPhone: +972-50-123"
            in build_ics(appt, ctx)
        )

    def test_details_alone_produce_description(self):
        from fsm.notifications.adapters.ics import build_ics

        appt = _make_appointment(
            start=datetime(2025, 6, 10, 9, 0, tzinfo=timezone.utc),
            end=datetime(2025, 6, 10, 10, 0, tzinfo=timezone.utc),
            details="Gate code 4321",
        )
        assert "DESCRIPTION:Gate code 4321" in build_ics(appt, AppointmentContext())

    def test_technician_lines_lead_description_before_problem(self):
        from fsm.notifications.adapters.ics import build_ics

        ctx = AppointmentContext(
            problem_description="No hot water",
            customer_phone="+972-50-123",
            technician_name="Grace Hopper",
            technician_phone="+972-50-999",
        )
        unfolded = build_ics(self._appt(), ctx).replace("\r\n ", "")
        assert (
            "DESCRIPTION:Technician: Grace Hopper\\nTechnician phone: +972-50-999"
            "\\nNo hot water\\nPhone: +972-50-123"
            in unfolded
        )

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


class TestBuildIcsItip:
    def _appt(self, created=None, updated=None):
        base = datetime(2025, 6, 1, tzinfo=timezone.utc)
        return _FakeAppointment(
            id=uuid.uuid4(),
            time_range=_FakeTimeRange(
                start=datetime(2025, 6, 10, 9, 0, tzinfo=timezone.utc),
                end=datetime(2025, 6, 10, 10, 0, tzinfo=timezone.utc),
            ),
            created_at=created or base,
            updated_at=updated or base,
        )

    def test_sequence_from_updated_minus_created(self):
        from fsm.notifications.adapters.ics import build_ics

        appt = self._appt(
            created=datetime(2025, 6, 1, 0, 0, 0, tzinfo=timezone.utc),
            updated=datetime(2025, 6, 1, 0, 0, 30, tzinfo=timezone.utc),
        )
        assert "SEQUENCE:30" in build_ics(appt, AppointmentContext())

    def test_request_method_when_organizer_and_attendee_present(self):
        from fsm.notifications.adapters.ics import build_ics

        result = build_ics(
            self._appt(), AppointmentContext(),
            method="REQUEST", organizer="ops@fsm.example", attendee="cara@example.com",
        )
        assert "METHOD:REQUEST" in result
        assert "STATUS:CONFIRMED" in result
        assert "ORGANIZER:mailto:ops@fsm.example" in result

        lines = result.split("\r\n")
        start = next(i for i, line in enumerate(lines) if line.startswith("ATTENDEE"))
        folded = [lines[start]]
        i = start + 1
        while i < len(lines) and lines[i].startswith(" "):
            folded.append(lines[i][1:])
            i += 1
        assert "".join(folded) == (
            "ATTENDEE;ROLE=REQ-PARTICIPANT;PARTSTAT=NEEDS-ACTION;RSVP=TRUE:mailto:cara@example.com"
        )

    def test_no_physical_line_exceeds_75_octets(self):
        from fsm.notifications.adapters.ics import build_ics

        result = build_ics(
            self._appt(), AppointmentContext(),
            method="REQUEST", organizer="ops@fsm.example", attendee="cara.mcdonald@example.com",
        )
        for line in result.split("\r\n"):
            assert len(line.encode("utf-8")) <= 75

    def test_cancel_method_sets_cancelled_status(self):
        from fsm.notifications.adapters.ics import build_ics

        result = build_ics(
            self._appt(), AppointmentContext(),
            method="CANCEL", organizer="ops@fsm.example", attendee="cara@example.com",
        )
        assert "METHOD:CANCEL" in result
        assert "STATUS:CANCELLED" in result

    def test_method_line_precedes_vevent(self):
        from fsm.notifications.adapters.ics import build_ics

        result = build_ics(
            self._appt(), AppointmentContext(),
            method="REQUEST", organizer="ops@fsm.example", attendee="cara@example.com",
        )
        assert result.index("METHOD:REQUEST") < result.index("BEGIN:VEVENT")

    def test_sequence_is_higher_for_a_reschedule_than_the_original_booking(self):
        """A reschedule (updated_at > created_at) must outrank the original booking's SEQUENCE:0,
        so a calendar client applies it as an update to the same entry rather than a duplicate."""
        from fsm.notifications.adapters.ics import build_ics

        def sequence_of(ics: str) -> int:
            line = next(line for line in ics.split("\r\n") if line.startswith("SEQUENCE:"))
            return int(line.removeprefix("SEQUENCE:"))

        created = datetime(2025, 6, 1, tzinfo=timezone.utc)
        original_booking = self._appt(created=created, updated=created)
        rescheduled = self._appt(created=created, updated=created + timedelta(seconds=300))

        original_sequence = sequence_of(build_ics(original_booking, AppointmentContext()))
        rescheduled_sequence = sequence_of(build_ics(rescheduled, AppointmentContext()))

        assert original_sequence == 0
        assert rescheduled_sequence == 300
        assert rescheduled_sequence > original_sequence

    def test_dtstamp_advances_for_a_reschedule_than_the_original_booking(self):
        """A reschedule (updated_at > created_at) must produce a strictly higher DTSTAMP than the
        original booking, so a calendar client applies it as an update even when the rescheduled
        time itself moves earlier than the original start."""
        from fsm.notifications.adapters.ics import build_ics

        def dtstamp_of(ics: str) -> str:
            line = next(line for line in ics.split("\r\n") if line.startswith("DTSTAMP:"))
            return line.removeprefix("DTSTAMP:")

        created = datetime(2025, 6, 1, tzinfo=timezone.utc)
        original_booking = self._appt(created=created, updated=created)
        rescheduled = self._appt(created=created, updated=created + timedelta(seconds=300))

        original_dtstamp = dtstamp_of(build_ics(original_booking, AppointmentContext()))
        rescheduled_dtstamp = dtstamp_of(build_ics(rescheduled, AppointmentContext()))

        assert rescheduled_dtstamp > original_dtstamp

    def test_no_itip_fields_when_organizer_or_attendee_blank(self):
        from fsm.notifications.adapters.ics import build_ics

        only_org = build_ics(self._appt(), AppointmentContext(), organizer="ops@fsm.example")
        both_blank = build_ics(self._appt(), AppointmentContext())
        for result in (only_org, both_blank):
            assert "METHOD" not in result
            assert "ORGANIZER" not in result
            assert "ATTENDEE" not in result
            assert "STATUS" not in result
            assert "SEQUENCE:0" in result  # SEQUENCE is always present
