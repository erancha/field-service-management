"""Port contract tests for in-memory fake implementations.

These tests verify that each fake honours the protocol contract. They double
as the contract test suite that any future concrete adapter must also satisfy.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from fsm.scheduling.domain import (
    Appointment,
    AppointmentStatus,
    NotFoundError,
    ServiceCall,
    ServiceCallStatus,
    TimeRange,
)
from fsm.scheduling.ports import (
    AppointmentRepository,
    CalendarPort,
    NotificationPort,
    ServiceCallRepository,
)
from tests.scheduling.fakes import (
    FakeCalendarPort,
    FakeNotificationPort,
    InMemoryAppointmentRepository,
    InMemoryServiceCallRepository,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utc(year: int, month: int, day: int, hour: int = 0) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


def _make_service_call(*, status: ServiceCallStatus = ServiceCallStatus.OPEN) -> ServiceCall:
    return ServiceCall(
        id=uuid.uuid4(),
        customer_id=uuid.uuid4(),
        description="Fix boiler",
        status=status,
        created_at=_utc(2024, 1, 1),
    )


def _make_appointment(
    *,
    technician_id: uuid.UUID | None = None,
    time_range: TimeRange | None = None,
    status: AppointmentStatus = AppointmentStatus.SCHEDULED,
) -> Appointment:
    if technician_id is None:
        technician_id = uuid.uuid4()
    if time_range is None:
        time_range = TimeRange(start=_utc(2024, 6, 1, 9), end=_utc(2024, 6, 1, 11))
    return Appointment(
        id=uuid.uuid4(),
        service_call_id=uuid.uuid4(),
        technician_id=technician_id,
        customer_id=uuid.uuid4(),
        time_range=time_range,
        status=status,
        details=None,
        created_at=_utc(2024, 1, 1),
        updated_at=_utc(2024, 1, 1),
    )


# ---------------------------------------------------------------------------
# ServiceCallRepository
# ---------------------------------------------------------------------------

class TestInMemoryServiceCallRepository:
    def test_add_then_get_round_trips(self):
        repo = InMemoryServiceCallRepository()
        sc = _make_service_call()
        repo.add(sc)
        fetched = repo.get(sc.id)
        assert fetched is sc

    def test_get_missing_raises_not_found(self):
        repo = InMemoryServiceCallRepository()
        with pytest.raises(NotFoundError):
            repo.get(uuid.uuid4())

    def test_save_persists_mutation(self):
        repo = InMemoryServiceCallRepository()
        sc = _make_service_call()
        repo.add(sc)
        sc.mark_scheduled()
        repo.save(sc)
        assert repo.get(sc.id).status is ServiceCallStatus.SCHEDULED

    def test_isinstance_satisfies_protocol(self):
        assert isinstance(InMemoryServiceCallRepository(), ServiceCallRepository)


# ---------------------------------------------------------------------------
# AppointmentRepository
# ---------------------------------------------------------------------------

class TestInMemoryAppointmentRepository:
    def test_add_then_get_round_trips(self):
        repo = InMemoryAppointmentRepository()
        appt = _make_appointment()
        repo.add(appt)
        assert repo.get(appt.id) is appt

    def test_get_missing_raises_not_found(self):
        repo = InMemoryAppointmentRepository()
        with pytest.raises(NotFoundError):
            repo.get(uuid.uuid4())

    def test_save_persists_mutation(self):
        repo = InMemoryAppointmentRepository()
        appt = _make_appointment()
        repo.add(appt)
        new_range = TimeRange(start=_utc(2024, 6, 2, 9), end=_utc(2024, 6, 2, 11))
        appt.reschedule(new_range, now=_utc(2024, 6, 2, 8))
        repo.save(appt)
        assert repo.get(appt.id).status is AppointmentStatus.RESCHEDULED

    def test_isinstance_satisfies_protocol(self):
        assert isinstance(InMemoryAppointmentRepository(), AppointmentRepository)

    # list_for_technician_between -------------------------------------------

    def test_list_returns_overlapping_appointment(self):
        repo = InMemoryAppointmentRepository()
        tech = uuid.uuid4()
        appt = _make_appointment(
            technician_id=tech,
            time_range=TimeRange(_utc(2024, 6, 1, 9), _utc(2024, 6, 1, 11)),
        )
        repo.add(appt)
        result = repo.list_for_technician_between(tech, _utc(2024, 6, 1, 8), _utc(2024, 6, 1, 10))
        assert appt in result

    def test_list_excludes_non_overlapping(self):
        repo = InMemoryAppointmentRepository()
        tech = uuid.uuid4()
        appt = _make_appointment(
            technician_id=tech,
            time_range=TimeRange(_utc(2024, 6, 1, 14), _utc(2024, 6, 1, 16)),
        )
        repo.add(appt)
        result = repo.list_for_technician_between(tech, _utc(2024, 6, 1, 8), _utc(2024, 6, 1, 12))
        assert appt not in result

    def test_list_excludes_cancelled(self):
        repo = InMemoryAppointmentRepository()
        tech = uuid.uuid4()
        appt = _make_appointment(
            technician_id=tech,
            time_range=TimeRange(_utc(2024, 6, 1, 9), _utc(2024, 6, 1, 11)),
            status=AppointmentStatus.CANCELLED,
        )
        repo.add(appt)
        result = repo.list_for_technician_between(tech, _utc(2024, 6, 1, 8), _utc(2024, 6, 1, 12))
        assert appt not in result

    def test_list_excludes_other_technician(self):
        repo = InMemoryAppointmentRepository()
        tech_a = uuid.uuid4()
        tech_b = uuid.uuid4()
        appt = _make_appointment(
            technician_id=tech_b,
            time_range=TimeRange(_utc(2024, 6, 1, 9), _utc(2024, 6, 1, 11)),
        )
        repo.add(appt)
        result = repo.list_for_technician_between(tech_a, _utc(2024, 6, 1, 8), _utc(2024, 6, 1, 12))
        assert appt not in result

    def test_list_includes_rescheduled_appointment(self):
        repo = InMemoryAppointmentRepository()
        tech = uuid.uuid4()
        appt = _make_appointment(
            technician_id=tech,
            time_range=TimeRange(_utc(2024, 6, 1, 9), _utc(2024, 6, 1, 11)),
            status=AppointmentStatus.RESCHEDULED,
        )
        repo.add(appt)
        result = repo.list_for_technician_between(tech, _utc(2024, 6, 1, 8), _utc(2024, 6, 1, 12))
        assert appt in result

    # Half-open boundary contract -------------------------------------------

    def test_appointment_ending_exactly_at_window_start_is_excluded(self):
        """Appointment [09:00, 11:00) ending at window start 11:00 is NOT in the result."""
        repo = InMemoryAppointmentRepository()
        tech = uuid.uuid4()
        appt = _make_appointment(
            technician_id=tech,
            time_range=TimeRange(_utc(2024, 6, 1, 9), _utc(2024, 6, 1, 11)),
        )
        repo.add(appt)
        result = repo.list_for_technician_between(tech, _utc(2024, 6, 1, 11), _utc(2024, 6, 1, 13))
        assert appt not in result

    def test_appointment_starting_exactly_at_window_end_is_excluded(self):
        """Appointment [13:00, 15:00) starting at window end 13:00 is NOT in the result."""
        repo = InMemoryAppointmentRepository()
        tech = uuid.uuid4()
        appt = _make_appointment(
            technician_id=tech,
            time_range=TimeRange(_utc(2024, 6, 1, 13), _utc(2024, 6, 1, 15)),
        )
        repo.add(appt)
        result = repo.list_for_technician_between(tech, _utc(2024, 6, 1, 9), _utc(2024, 6, 1, 13))
        assert appt not in result

    def test_appointment_overlapping_by_instant_is_included(self):
        """Appointment [10:00, 12:00) sharing time [11:00, 12:00) with window [11:00, 13:00) IS included."""
        repo = InMemoryAppointmentRepository()
        tech = uuid.uuid4()
        appt = _make_appointment(
            technician_id=tech,
            time_range=TimeRange(_utc(2024, 6, 1, 10), _utc(2024, 6, 1, 12)),
        )
        repo.add(appt)
        result = repo.list_for_technician_between(tech, _utc(2024, 6, 1, 11), _utc(2024, 6, 1, 13))
        assert appt in result


# ---------------------------------------------------------------------------
# FakeCalendarPort
# ---------------------------------------------------------------------------

class TestFakeCalendarPort:
    def test_get_busy_returns_set_ranges(self):
        cal = FakeCalendarPort()
        tech = uuid.uuid4()
        ranges = [
            TimeRange(_utc(2024, 6, 1, 9), _utc(2024, 6, 1, 10)),
            TimeRange(_utc(2024, 6, 1, 14), _utc(2024, 6, 1, 15)),
        ]
        cal.set_busy(tech, ranges)
        result = cal.get_busy(tech, _utc(2024, 6, 1), _utc(2024, 6, 2))
        assert result == ranges

    def test_get_busy_returns_empty_for_unknown_technician(self):
        cal = FakeCalendarPort()
        result = cal.get_busy(uuid.uuid4(), _utc(2024, 6, 1), _utc(2024, 6, 2))
        assert result == []

    def test_create_event_returns_deterministic_sequential_ids(self):
        cal = FakeCalendarPort()
        appt1 = _make_appointment()
        appt2 = _make_appointment()
        id1 = cal.create_event(appt1)
        id2 = cal.create_event(appt2)
        assert id1 == "evt-1"
        assert id2 == "evt-2"

    def test_create_event_records_appointment(self):
        cal = FakeCalendarPort()
        appt = _make_appointment()
        event_id = cal.create_event(appt)
        assert cal.created_events[event_id] is appt

    def test_update_event_records_appointment(self):
        cal = FakeCalendarPort()
        appt = _make_appointment()
        event_id = cal.create_event(appt)
        cal.update_event(event_id, appt)
        assert cal.updated_events[event_id] is appt

    def test_delete_event_records_event_id(self):
        cal = FakeCalendarPort()
        appt = _make_appointment()
        event_id = cal.create_event(appt)
        cal.delete_event(event_id)
        assert event_id in cal.deleted_event_ids

    def test_isinstance_satisfies_protocol(self):
        assert isinstance(FakeCalendarPort(), CalendarPort)


# ---------------------------------------------------------------------------
# FakeNotificationPort
# ---------------------------------------------------------------------------

class TestFakeNotificationPort:
    def test_appointment_booked_recorded(self):
        notif = FakeNotificationPort()
        appt = _make_appointment()
        notif.appointment_booked(appt)
        assert ("booked", appt) in notif.calls

    def test_appointment_rescheduled_recorded(self):
        notif = FakeNotificationPort()
        appt = _make_appointment()
        notif.appointment_rescheduled(appt)
        assert ("rescheduled", appt) in notif.calls

    def test_appointment_cancelled_recorded(self):
        notif = FakeNotificationPort()
        appt = _make_appointment()
        notif.appointment_cancelled(appt)
        assert ("cancelled", appt) in notif.calls

    def test_multiple_calls_recorded_in_order(self):
        notif = FakeNotificationPort()
        appt1 = _make_appointment()
        appt2 = _make_appointment()
        notif.appointment_booked(appt1)
        notif.appointment_rescheduled(appt2)
        assert notif.calls[0] == ("booked", appt1)
        assert notif.calls[1] == ("rescheduled", appt2)

    def test_isinstance_satisfies_protocol(self):
        assert isinstance(FakeNotificationPort(), NotificationPort)
