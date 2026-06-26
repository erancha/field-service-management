"""Tests for Appointment entity and AppointmentStatus enum."""
import uuid
from datetime import datetime, timedelta, timezone
import pytest

from fsm.scheduling.domain import (
    Appointment,
    AppointmentStatus,
    TimeRange,
    InvalidTransition,
)


_CREATED_AT = datetime(2024, 6, 10, 8, 0, tzinfo=timezone.utc)
_UPDATED_AT = datetime(2024, 6, 10, 8, 0, tzinfo=timezone.utc)
_NOW = datetime(2024, 6, 10, 9, 0, tzinfo=timezone.utc)


def _dt(hour: int, minute: int = 0) -> datetime:
    return datetime(2024, 6, 10, hour, minute, tzinfo=timezone.utc)


def _range(start_h: int, end_h: int) -> TimeRange:
    return TimeRange(start=_dt(start_h), end=_dt(end_h))


def _new_appointment(**kwargs) -> Appointment:
    defaults = dict(
        id=uuid.uuid4(),
        service_call_id=uuid.uuid4(),
        technician_id=uuid.uuid4(),
        customer_id=uuid.uuid4(),
        time_range=_range(9, 11),
        status=AppointmentStatus.SCHEDULED,
        details=None,
        created_at=_CREATED_AT,
        updated_at=_UPDATED_AT,
    )
    defaults.update(kwargs)
    return Appointment(**defaults)


class TestAppointmentCreation:
    def test_creates_with_scheduled_status(self):
        appt = _new_appointment()
        assert appt.status == AppointmentStatus.SCHEDULED

    def test_fields_accessible(self):
        appt_id = uuid.uuid4()
        sc_id = uuid.uuid4()
        tech_id = uuid.uuid4()
        cust_id = uuid.uuid4()
        tr = _range(10, 12)
        appt = _new_appointment(
            id=appt_id,
            service_call_id=sc_id,
            technician_id=tech_id,
            customer_id=cust_id,
            time_range=tr,
        )
        assert appt.id == appt_id
        assert appt.service_call_id == sc_id
        assert appt.technician_id == tech_id
        assert appt.customer_id == cust_id
        assert appt.time_range == tr
        assert appt.details is None


class TestAppointmentReschedule:
    def test_reschedule_changes_range_and_status(self):
        appt = _new_appointment()
        new_range = _range(14, 16)
        appt.reschedule(new_range, now=_NOW)
        assert appt.time_range == new_range
        assert appt.status == AppointmentStatus.RESCHEDULED

    def test_reschedule_updates_updated_at_strictly(self):
        appt = _new_appointment()
        later = _UPDATED_AT + timedelta(seconds=1)
        appt.reschedule(_range(14, 16), now=later)
        assert appt.updated_at == later

    def test_reschedule_on_cancelled_raises(self):
        appt = _new_appointment()
        appt.cancel(now=_NOW)
        with pytest.raises(InvalidTransition):
            appt.reschedule(_range(14, 16), now=_NOW)

    def test_rescheduled_can_be_rescheduled_again(self):
        appt = _new_appointment()
        appt.reschedule(_range(14, 16), now=_NOW)
        appt.reschedule(_range(15, 17), now=_NOW)
        assert appt.time_range == _range(15, 17)
        assert appt.status == AppointmentStatus.RESCHEDULED


class TestAppointmentCancel:
    def test_cancel_sets_cancelled_status(self):
        appt = _new_appointment()
        appt.cancel(now=_NOW)
        assert appt.status == AppointmentStatus.CANCELLED

    def test_cancel_on_rescheduled_works(self):
        appt = _new_appointment()
        appt.reschedule(_range(14, 16), now=_NOW)
        appt.cancel(now=_NOW)
        assert appt.status == AppointmentStatus.CANCELLED

    def test_cancel_on_cancelled_raises(self):
        appt = _new_appointment()
        appt.cancel(now=_NOW)
        with pytest.raises(InvalidTransition):
            appt.cancel(now=_NOW)

    def test_cancel_updates_updated_at_strictly(self):
        appt = _new_appointment()
        later = _UPDATED_AT + timedelta(seconds=5)
        appt.cancel(now=later)
        assert appt.updated_at == later


class TestAppointmentAddDetails:
    def test_add_details_sets_text(self):
        appt = _new_appointment()
        appt.add_details("Bring ladder and toolkit", now=_NOW)
        assert appt.details == "Bring ladder and toolkit"

    def test_add_details_on_rescheduled_works(self):
        appt = _new_appointment()
        appt.reschedule(_range(14, 16), now=_NOW)
        appt.add_details("Updated notes", now=_NOW)
        assert appt.details == "Updated notes"

    def test_add_details_on_cancelled_raises(self):
        appt = _new_appointment()
        appt.cancel(now=_NOW)
        with pytest.raises(InvalidTransition):
            appt.add_details("Should not work", now=_NOW)

    def test_add_details_updates_updated_at_strictly(self):
        appt = _new_appointment()
        later = _UPDATED_AT + timedelta(minutes=1)
        appt.add_details("Some detail", now=later)
        assert appt.updated_at == later


class TestExternalEventId:
    def test_defaults_to_none(self):
        appt = _new_appointment()
        assert appt.external_event_id is None

    def test_assign_external_event_stores_id(self):
        appt = _new_appointment()
        appt.assign_external_event("evt-42")
        assert appt.external_event_id == "evt-42"

    def test_assign_external_event_is_replaceable(self):
        appt = _new_appointment()
        appt.assign_external_event("evt-1")
        appt.assign_external_event("evt-2")
        assert appt.external_event_id == "evt-2"


class TestCancelledIsTerminal:
    def test_reschedule_after_cancel_raises(self):
        appt = _new_appointment()
        appt.cancel(now=_NOW)
        with pytest.raises(InvalidTransition):
            appt.reschedule(_range(14, 16), now=_NOW)

    def test_cancel_after_cancel_raises(self):
        appt = _new_appointment()
        appt.cancel(now=_NOW)
        with pytest.raises(InvalidTransition):
            appt.cancel(now=_NOW)

    def test_add_details_after_cancel_raises(self):
        appt = _new_appointment()
        appt.cancel(now=_NOW)
        with pytest.raises(InvalidTransition):
            appt.add_details("Ignored", now=_NOW)
