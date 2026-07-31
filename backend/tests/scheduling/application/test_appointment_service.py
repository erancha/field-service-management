"""Tests for AppointmentService application use cases."""
from __future__ import annotations

import zoneinfo
from datetime import date, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from fsm.scheduling.application import AppointmentService
from fsm.scheduling.domain import (
    Appointment,
    AppointmentStatus,
    BookingRateLimited,
    CancellationRateLimit,
    ContactInfo,
    IncompleteContactInfo,
    InvalidTransition,
    NotFoundError,
    ServiceCall,
    ServiceCallStatus,
    SlotUnavailable,
    TimeRange,
    WeeklyWorkingHours,
)
from fsm.scheduling.ports.outbox import OutboxOperation
from tests.scheduling.fakes import (
    FakeCalendarPort,
    FakeNotificationPort,
    InMemoryAppointmentRepository,
    InMemoryOutboxRepository,
    InMemoryServiceCallRepository,
)

# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------

_TZ = timezone.utc
_FIXED_NOW = datetime(2024, 6, 10, 8, 0, tzinfo=_TZ)
_APPT_ID = UUID("aaaaaaaa-0000-0000-0000-000000000001")
_SC_ID = UUID("bbbbbbbb-0000-0000-0000-000000000001")
_TECH_ID = UUID("cccccccc-0000-0000-0000-000000000001")
_CUST_ID = UUID("dddddddd-0000-0000-0000-000000000001")


def _tr(start_h: int, end_h: int, day: int = 10) -> TimeRange:
    return TimeRange(
        start=datetime(2024, 6, day, start_h, 0, tzinfo=_TZ),
        end=datetime(2024, 6, day, end_h, 0, tzinfo=_TZ),
    )


@pytest.fixture
def appt_repo() -> InMemoryAppointmentRepository:
    return InMemoryAppointmentRepository()


@pytest.fixture
def sc_repo() -> InMemoryServiceCallRepository:
    return InMemoryServiceCallRepository()


@pytest.fixture
def calendar() -> FakeCalendarPort:
    return FakeCalendarPort()


@pytest.fixture
def notifications() -> FakeNotificationPort:
    return FakeNotificationPort()


@pytest.fixture
def outbox() -> InMemoryOutboxRepository:
    return InMemoryOutboxRepository()


def _complete_contact(_user_id: UUID) -> ContactInfo:
    """Contact resolver returning full contact for every id, so booking passes the precondition."""
    return ContactInfo(address="12 Main St", phone="+972-50-1")


@pytest.fixture
def svc(
    appt_repo: InMemoryAppointmentRepository,
    sc_repo: InMemoryServiceCallRepository,
    calendar: FakeCalendarPort,
    notifications: FakeNotificationPort,
    outbox: InMemoryOutboxRepository,
) -> AppointmentService:
    return AppointmentService(
        appointments=appt_repo,
        service_calls=sc_repo,
        calendar=calendar,
        notifications=notifications,
        outbox=outbox,
        clock=lambda: _FIXED_NOW,
        new_id=lambda: _APPT_ID,
        contact_resolver=_complete_contact,
    )


def _seed_open_service_call(sc_repo: InMemoryServiceCallRepository) -> ServiceCall:
    sc = ServiceCall(
        id=_SC_ID,
        customer_id=_CUST_ID,
        description="Boiler repair",
        status=ServiceCallStatus.OPEN,
        created_at=_FIXED_NOW,
    )
    sc_repo.add(sc)
    return sc


# ---------------------------------------------------------------------------
# propose_slots
# ---------------------------------------------------------------------------


class TestProposeSlots:
    def test_returns_free_slots_excluding_calendar_busy(
        self,
        svc: AppointmentService,
        calendar: FakeCalendarPort,
    ):
        # Mon 2024-06-10 is a default working day (Sun-Thu); the 08:00 clock is before
        # the 09:00 window start, so no slot is dropped as past.
        start_date = date(2024, 6, 10)
        end_date = date(2024, 6, 10)
        wh = WeeklyWorkingHours.default()

        # Mark 09:00-10:00 busy in calendar
        busy_range = TimeRange(
            start=datetime(2024, 6, 10, 9, 0, tzinfo=_TZ),
            end=datetime(2024, 6, 10, 10, 0, tzinfo=_TZ),
        )
        calendar.set_busy(_TECH_ID, [busy_range])

        slots = svc.propose_slots(
            technician_id=_TECH_ID,
            working_hours=wh,
            tz=_TZ,
            start_date=start_date,
            end_date=end_date,
            slot_duration=timedelta(hours=1),
        )

        # 09:00 slot must be excluded; 10:00-17:00 is 7 hours = 7 slots
        assert all(s.start >= datetime(2024, 6, 10, 10, 0, tzinfo=_TZ) for s in slots)
        assert len(slots) == 7

    def test_returns_free_slots_excluding_existing_appointments(
        self,
        svc: AppointmentService,
        appt_repo: InMemoryAppointmentRepository,
    ):
        start_date = date(2024, 6, 10)
        end_date = date(2024, 6, 10)
        wh = WeeklyWorkingHours.default()

        # Seed an appointment that occupies 10:00-11:00
        appt = Appointment(
            id=UUID("eeeeeeee-0000-0000-0000-000000000001"),
            service_call_id=_SC_ID,
            technician_id=_TECH_ID,
            customer_id=_CUST_ID,
            time_range=TimeRange(
                start=datetime(2024, 6, 10, 10, 0, tzinfo=_TZ),
                end=datetime(2024, 6, 10, 11, 0, tzinfo=_TZ),
            ),
            status=AppointmentStatus.SCHEDULED,
            details=None,
            created_at=_FIXED_NOW,
            updated_at=_FIXED_NOW,
        )
        appt_repo.add(appt)

        slots = svc.propose_slots(
            technician_id=_TECH_ID,
            working_hours=wh,
            tz=_TZ,
            start_date=start_date,
            end_date=end_date,
            slot_duration=timedelta(hours=1),
        )

        # 10:00 slot must be absent; default day gives 09-17 = 8 slots minus 1 = 7
        slot_starts = [s.start.hour for s in slots]
        assert 10 not in slot_starts
        assert len(slots) == 7

    def test_combines_calendar_busy_and_existing_appointments(
        self,
        svc: AppointmentService,
        appt_repo: InMemoryAppointmentRepository,
        calendar: FakeCalendarPort,
    ):
        start_date = date(2024, 6, 10)
        end_date = date(2024, 6, 10)
        wh = WeeklyWorkingHours.default()

        # Calendar busy: 09:00-10:00
        calendar.set_busy(
            _TECH_ID,
            [TimeRange(
                start=datetime(2024, 6, 10, 9, 0, tzinfo=_TZ),
                end=datetime(2024, 6, 10, 10, 0, tzinfo=_TZ),
            )],
        )
        # Appointment busy: 11:00-12:00
        appt = Appointment(
            id=UUID("eeeeeeee-0000-0000-0000-000000000002"),
            service_call_id=_SC_ID,
            technician_id=_TECH_ID,
            customer_id=_CUST_ID,
            time_range=TimeRange(
                start=datetime(2024, 6, 10, 11, 0, tzinfo=_TZ),
                end=datetime(2024, 6, 10, 12, 0, tzinfo=_TZ),
            ),
            status=AppointmentStatus.SCHEDULED,
            details=None,
            created_at=_FIXED_NOW,
            updated_at=_FIXED_NOW,
        )
        appt_repo.add(appt)

        slots = svc.propose_slots(
            technician_id=_TECH_ID,
            working_hours=wh,
            tz=_TZ,
            start_date=start_date,
            end_date=end_date,
            slot_duration=timedelta(hours=1),
        )

        slot_starts = [s.start.hour for s in slots]
        assert 9 not in slot_starts
        assert 11 not in slot_starts
        assert len(slots) == 6

    def test_excludes_slots_that_begin_before_now(
        self,
        appt_repo: InMemoryAppointmentRepository,
        sc_repo: InMemoryServiceCallRepository,
        calendar: FakeCalendarPort,
        notifications: FakeNotificationPort,
        outbox: InMemoryOutboxRepository,
    ):
        # Mon 2024-06-10 mid-window: slots starting before 12:30 are in the past.
        now = datetime(2024, 6, 10, 12, 30, tzinfo=_TZ)
        svc = AppointmentService(
            appointments=appt_repo,
            service_calls=sc_repo,
            calendar=calendar,
            notifications=notifications,
            outbox=outbox,
            clock=lambda: now,
            new_id=lambda: _APPT_ID,
            contact_resolver=_complete_contact,
        )
        wh = WeeklyWorkingHours.default()

        slots = svc.propose_slots(
            technician_id=_TECH_ID,
            working_hours=wh,
            tz=_TZ,
            start_date=date(2024, 6, 10),
            end_date=date(2024, 6, 10),
            slot_duration=timedelta(hours=1),
        )

        # 09:00–12:00 slots begin before 12:30 and are excluded; 13:00–16:00 remain.
        assert all(s.start >= now for s in slots)
        assert [s.start.hour for s in slots] == [13, 14, 15, 16]


# ---------------------------------------------------------------------------
# book_appointment
# ---------------------------------------------------------------------------


class TestBookAppointment:
    def test_persists_scheduled_appointment(
        self,
        svc: AppointmentService,
        appt_repo: InMemoryAppointmentRepository,
        sc_repo: InMemoryServiceCallRepository,
    ):
        _seed_open_service_call(sc_repo)
        tr = _tr(9, 11)
        appt = svc.book_appointment(
            service_call_id=_SC_ID,
            technician_id=_TECH_ID,
            customer_id=_CUST_ID,
            time_range=tr,
        )
        stored = appt_repo.get(appt.id)
        assert stored.status == AppointmentStatus.SCHEDULED
        assert stored.time_range == tr

    def test_enqueues_create_outbox_entry_and_no_synchronous_calendar_call(
        self,
        svc: AppointmentService,
        calendar: FakeCalendarPort,
        sc_repo: InMemoryServiceCallRepository,
        appt_repo: InMemoryAppointmentRepository,
        outbox: InMemoryOutboxRepository,
    ):
        """book_appointment must enqueue a CREATE outbox entry and NOT call create_event."""
        _seed_open_service_call(sc_repo)
        appt = svc.book_appointment(
            service_call_id=_SC_ID,
            technician_id=_TECH_ID,
            customer_id=_CUST_ID,
            time_range=_tr(9, 11),
        )

        # No synchronous calendar call
        assert len(calendar.created_events) == 0

        # external_event_id is None at booking time; dispatcher sets it later
        assert appt.external_event_id is None
        stored = appt_repo.get(appt.id)
        assert stored.external_event_id is None

        # Exactly one CREATE outbox entry for this appointment
        entries = outbox.all_entries
        assert len(entries) == 1
        assert entries[0].operation is OutboxOperation.CREATE
        assert entries[0].appointment_id == appt.id

    def test_transitions_service_call_to_scheduled(
        self,
        svc: AppointmentService,
        sc_repo: InMemoryServiceCallRepository,
    ):
        _seed_open_service_call(sc_repo)
        svc.book_appointment(
            service_call_id=_SC_ID,
            technician_id=_TECH_ID,
            customer_id=_CUST_ID,
            time_range=_tr(9, 11),
        )
        sc = sc_repo.get(_SC_ID)
        assert sc.status == ServiceCallStatus.SCHEDULED

    def test_records_booked_notification(
        self,
        svc: AppointmentService,
        sc_repo: InMemoryServiceCallRepository,
        notifications: FakeNotificationPort,
    ):
        _seed_open_service_call(sc_repo)
        appt = svc.book_appointment(
            service_call_id=_SC_ID,
            technician_id=_TECH_ID,
            customer_id=_CUST_ID,
            time_range=_tr(9, 11),
        )
        assert notifications.calls == [("booked", appt)]

    def test_both_db_writes_and_outbox_enqueue_occur_before_notification(
        self,
        sc_repo: InMemoryServiceCallRepository,
        appt_repo: InMemoryAppointmentRepository,
        outbox: InMemoryOutboxRepository,
        notifications: FakeNotificationPort,
        calendar: FakeCalendarPort,
    ):
        """Both appointments.add and service_calls.save complete before the notification fires.

        We also verify the outbox entry exists at notification time.
        """
        _seed_open_service_call(sc_repo)

        snapshots: dict[str, object] = {}

        class CapturingNotifications:
            def appointment_booked(self, appt: Appointment) -> None:
                try:
                    snapshots["appt_row"] = appt_repo.get(appt.id)
                except Exception as exc:
                    snapshots["appt_row"] = exc
                try:
                    sc = sc_repo.get(_SC_ID)
                    snapshots["sc_status"] = sc.status
                except Exception as exc:
                    snapshots["sc_status"] = exc
                snapshots["outbox_entries"] = list(outbox.all_entries)

            def appointment_rescheduled(self, appt: Appointment) -> None:
                pass

            def appointment_cancelled(self, appt: Appointment) -> None:
                pass

        svc2 = AppointmentService(
            appointments=appt_repo,
            service_calls=sc_repo,
            calendar=calendar,
            notifications=CapturingNotifications(),
            outbox=outbox,
            clock=lambda: _FIXED_NOW,
            new_id=lambda: _APPT_ID,
            contact_resolver=_complete_contact,
        )
        svc2.book_appointment(
            service_call_id=_SC_ID,
            technician_id=_TECH_ID,
            customer_id=_CUST_ID,
            time_range=_tr(9, 11),
        )
        assert isinstance(snapshots.get("appt_row"), Appointment), (
            "appointments.add must fire before notification"
        )
        assert snapshots.get("sc_status") == ServiceCallStatus.SCHEDULED, (
            "service_calls.save must fire before notification"
        )
        entries = snapshots.get("outbox_entries", [])
        assert len(entries) == 1, "outbox.enqueue must fire before notification"

    def test_raises_slot_unavailable_when_overlapping_existing_appointment(
        self,
        svc: AppointmentService,
        appt_repo: InMemoryAppointmentRepository,
        sc_repo: InMemoryServiceCallRepository,
    ):
        _seed_open_service_call(sc_repo)
        # Pre-existing appointment 09:00-11:00
        existing = Appointment(
            id=UUID("eeeeeeee-0000-0000-0000-000000000003"),
            service_call_id=_SC_ID,
            technician_id=_TECH_ID,
            customer_id=_CUST_ID,
            time_range=_tr(9, 11),
            status=AppointmentStatus.SCHEDULED,
            details=None,
            created_at=_FIXED_NOW,
            updated_at=_FIXED_NOW,
        )
        appt_repo.add(existing)

        with pytest.raises(SlotUnavailable):
            svc.book_appointment(
                service_call_id=_SC_ID,
                technician_id=_TECH_ID,
                customer_id=_CUST_ID,
                time_range=_tr(10, 12),  # overlaps 09:00-11:00
            )

    def test_timestamps_from_clock(
        self,
        svc: AppointmentService,
        sc_repo: InMemoryServiceCallRepository,
    ):
        _seed_open_service_call(sc_repo)
        appt = svc.book_appointment(
            service_call_id=_SC_ID,
            technician_id=_TECH_ID,
            customer_id=_CUST_ID,
            time_range=_tr(9, 11),
        )
        assert appt.created_at == _FIXED_NOW
        assert appt.updated_at == _FIXED_NOW


# ---------------------------------------------------------------------------
# reschedule_appointment
# ---------------------------------------------------------------------------


class TestRescheduleAppointment:
    def _book(
        self,
        svc: AppointmentService,
        sc_repo: InMemoryServiceCallRepository,
        outbox: InMemoryOutboxRepository,
        time_range: TimeRange | None = None,
    ) -> Appointment:
        _seed_open_service_call(sc_repo)
        appt = svc.book_appointment(
            service_call_id=_SC_ID,
            technician_id=_TECH_ID,
            customer_id=_CUST_ID,
            time_range=time_range or _tr(9, 11),
        )
        # Clear the CREATE outbox entry so reschedule assertions are clean
        outbox._entries.clear()
        outbox._statuses.clear()
        return appt

    def test_changes_time_and_status_to_rescheduled(
        self,
        svc: AppointmentService,
        sc_repo: InMemoryServiceCallRepository,
        appt_repo: InMemoryAppointmentRepository,
        outbox: InMemoryOutboxRepository,
    ):
        appt = self._book(svc, sc_repo, outbox)
        new_range = _tr(13, 15)
        updated = svc.reschedule_appointment(appt.id, new_range)
        assert updated.time_range == new_range
        assert updated.status == AppointmentStatus.RESCHEDULED
        stored = appt_repo.get(appt.id)
        assert stored.time_range == new_range

    def test_enqueues_update_outbox_entry_no_synchronous_calendar_call(
        self,
        svc: AppointmentService,
        sc_repo: InMemoryServiceCallRepository,
        calendar: FakeCalendarPort,
        outbox: InMemoryOutboxRepository,
    ):
        """reschedule must enqueue an UPDATE entry and NOT call calendar.update_event."""
        appt = self._book(svc, sc_repo, outbox)
        svc.reschedule_appointment(appt.id, _tr(13, 15))

        assert len(calendar.updated_events) == 0

        entries = outbox.all_entries
        assert len(entries) == 1
        assert entries[0].operation is OutboxOperation.UPDATE
        assert entries[0].appointment_id == appt.id

    def test_records_rescheduled_notification(
        self,
        svc: AppointmentService,
        sc_repo: InMemoryServiceCallRepository,
        notifications: FakeNotificationPort,
        outbox: InMemoryOutboxRepository,
    ):
        appt = self._book(svc, sc_repo, outbox)
        notifications.calls.clear()
        updated = svc.reschedule_appointment(appt.id, _tr(13, 15))
        assert notifications.calls == [("rescheduled", updated)]

    def test_raises_slot_unavailable_on_conflict_with_different_appointment(
        self,
        svc: AppointmentService,
        sc_repo: InMemoryServiceCallRepository,
        appt_repo: InMemoryAppointmentRepository,
        outbox: InMemoryOutboxRepository,
    ):
        # Book the first appointment at 09:00-11:00
        appt1 = self._book(svc, sc_repo, outbox)

        # Seed a second appointment at 13:00-15:00 for the same technician
        existing2 = Appointment(
            id=UUID("eeeeeeee-0000-0000-0000-000000000004"),
            service_call_id=UUID("bbbbbbbb-0000-0000-0000-000000000002"),
            technician_id=_TECH_ID,
            customer_id=_CUST_ID,
            time_range=_tr(13, 15),
            status=AppointmentStatus.SCHEDULED,
            details=None,
            created_at=_FIXED_NOW,
            updated_at=_FIXED_NOW,
        )
        appt_repo.add(existing2)

        # Try to reschedule appt1 into 14:00-16:00, which overlaps existing2
        with pytest.raises(SlotUnavailable):
            svc.reschedule_appointment(appt1.id, _tr(14, 16))

    def test_self_overlap_is_allowed(
        self,
        svc: AppointmentService,
        sc_repo: InMemoryServiceCallRepository,
        outbox: InMemoryOutboxRepository,
    ):
        appt = self._book(svc, sc_repo, outbox, _tr(9, 11))
        # Rescheduling to an overlapping-but-different range should succeed
        # because self is excluded from conflict check
        updated = svc.reschedule_appointment(appt.id, _tr(10, 12))
        assert updated.status == AppointmentStatus.RESCHEDULED


# ---------------------------------------------------------------------------
# cancel_appointment
# ---------------------------------------------------------------------------


class TestCancelAppointment:
    def _book(
        self,
        svc: AppointmentService,
        sc_repo: InMemoryServiceCallRepository,
        outbox: InMemoryOutboxRepository,
    ) -> Appointment:
        _seed_open_service_call(sc_repo)
        appt = svc.book_appointment(
            service_call_id=_SC_ID,
            technician_id=_TECH_ID,
            customer_id=_CUST_ID,
            time_range=_tr(9, 11),
        )
        outbox._entries.clear()
        outbox._statuses.clear()
        return appt

    def test_cancels_appointment(
        self,
        svc: AppointmentService,
        sc_repo: InMemoryServiceCallRepository,
        appt_repo: InMemoryAppointmentRepository,
        outbox: InMemoryOutboxRepository,
    ):
        appt = self._book(svc, sc_repo, outbox)
        cancelled = svc.cancel_appointment(appt.id)
        assert cancelled.status == AppointmentStatus.CANCELLED
        stored = appt_repo.get(appt.id)
        assert stored.status == AppointmentStatus.CANCELLED

    def test_enqueues_delete_outbox_entry_no_synchronous_calendar_call(
        self,
        svc: AppointmentService,
        sc_repo: InMemoryServiceCallRepository,
        calendar: FakeCalendarPort,
        outbox: InMemoryOutboxRepository,
    ):
        """cancel must enqueue a DELETE entry and NOT call calendar.delete_event."""
        appt = self._book(svc, sc_repo, outbox)
        svc.cancel_appointment(appt.id)

        assert len(calendar.deleted_event_ids) == 0

        entries = outbox.all_entries
        assert len(entries) == 1
        assert entries[0].operation is OutboxOperation.DELETE
        assert entries[0].appointment_id == appt.id

    def test_cancel_captures_external_event_id_in_outbox_entry(
        self,
        appt_repo: InMemoryAppointmentRepository,
        sc_repo: InMemoryServiceCallRepository,
        calendar: FakeCalendarPort,
        notifications: FakeNotificationPort,
        outbox: InMemoryOutboxRepository,
    ):
        """external_event_id on the appointment at cancel time is stored in the outbox entry."""
        _seed_open_service_call(sc_repo)
        # Manually set an external_event_id on the appointment before cancel
        svc = AppointmentService(
            appointments=appt_repo,
            service_calls=sc_repo,
            calendar=calendar,
            notifications=notifications,
            outbox=outbox,
            clock=lambda: _FIXED_NOW,
            new_id=lambda: _APPT_ID,
            contact_resolver=_complete_contact,
        )
        svc.book_appointment(
            service_call_id=_SC_ID,
            technician_id=_TECH_ID,
            customer_id=_CUST_ID,
            time_range=_tr(9, 11),
        )
        # Simulate dispatcher having set the external_event_id
        appt = appt_repo.get(_APPT_ID)
        appt.assign_external_event("evt-abc")
        appt_repo.save(appt)

        outbox._entries.clear()
        outbox._statuses.clear()

        svc.cancel_appointment(_APPT_ID)

        entries = outbox.all_entries
        assert len(entries) == 1
        assert entries[0].operation is OutboxOperation.DELETE
        assert entries[0].external_event_id == "evt-abc"

    def test_records_cancelled_notification(
        self,
        svc: AppointmentService,
        sc_repo: InMemoryServiceCallRepository,
        notifications: FakeNotificationPort,
        outbox: InMemoryOutboxRepository,
    ):
        appt = self._book(svc, sc_repo, outbox)
        notifications.calls.clear()
        cancelled = svc.cancel_appointment(appt.id)
        assert notifications.calls == [("cancelled", cancelled)]


# ---------------------------------------------------------------------------
# add_details
# ---------------------------------------------------------------------------


class TestAddDetails:
    def _book(
        self,
        svc: AppointmentService,
        sc_repo: InMemoryServiceCallRepository,
        outbox: InMemoryOutboxRepository,
    ) -> Appointment:
        _seed_open_service_call(sc_repo)
        appt = svc.book_appointment(
            service_call_id=_SC_ID,
            technician_id=_TECH_ID,
            customer_id=_CUST_ID,
            time_range=_tr(9, 11),
        )
        outbox._entries.clear()
        outbox._statuses.clear()
        return appt

    def test_updates_details_and_enqueues_update_entry(
        self,
        svc: AppointmentService,
        sc_repo: InMemoryServiceCallRepository,
        calendar: FakeCalendarPort,
        appt_repo: InMemoryAppointmentRepository,
        outbox: InMemoryOutboxRepository,
    ):
        appt = self._book(svc, sc_repo, outbox)
        updated = svc.add_details(appt.id, "Bring ladder")
        assert updated.details == "Bring ladder"

        # No synchronous calendar call
        assert len(calendar.updated_events) == 0

        # One UPDATE outbox entry
        entries = outbox.all_entries
        assert len(entries) == 1
        assert entries[0].operation is OutboxOperation.UPDATE
        assert entries[0].appointment_id == appt.id

        stored = appt_repo.get(appt.id)
        assert stored.details == "Bring ladder"

    def test_add_details_emits_updated_notification_not_lifecycle_transition(
        self,
        svc: AppointmentService,
        sc_repo: InMemoryServiceCallRepository,
        notifications: FakeNotificationPort,
        outbox: InMemoryOutboxRepository,
    ):
        """Adding details fires appointment_updated so the customer's ICS invitation is re-sent;
        it is not a booked/rescheduled/cancelled lifecycle transition."""
        appt = self._book(svc, sc_repo, outbox)
        notifications.calls.clear()
        updated = svc.add_details(appt.id, "Bring ladder")
        assert [(kind, a.id) for kind, a in notifications.calls] == [("updated", updated.id)]


# ---------------------------------------------------------------------------
# book_appointment validates service call before any mutation
# ---------------------------------------------------------------------------


class TestBookAppointmentServiceCallValidation:
    def test_booking_nonexistent_service_call_raises_not_found(
        self,
        svc: AppointmentService,
        appt_repo: InMemoryAppointmentRepository,
        calendar: FakeCalendarPort,
        outbox: InMemoryOutboxRepository,
    ):
        missing_sc_id = UUID("ffff0000-0000-0000-0000-000000000001")
        with pytest.raises(NotFoundError):
            svc.book_appointment(
                service_call_id=missing_sc_id,
                technician_id=_TECH_ID,
                customer_id=_CUST_ID,
                time_range=_tr(9, 11),
            )
        assert len(calendar.created_events) == 0
        assert len(list(appt_repo._store)) == 0
        assert len(outbox.all_entries) == 0

    def test_booking_scheduled_service_call_raises_invalid_transition(
        self,
        svc: AppointmentService,
        sc_repo: InMemoryServiceCallRepository,
        appt_repo: InMemoryAppointmentRepository,
        calendar: FakeCalendarPort,
        outbox: InMemoryOutboxRepository,
    ):
        sc = ServiceCall(
            id=_SC_ID,
            customer_id=_CUST_ID,
            description="Boiler repair",
            status=ServiceCallStatus.SCHEDULED,
            created_at=_FIXED_NOW,
        )
        sc_repo.add(sc)
        with pytest.raises(InvalidTransition):
            svc.book_appointment(
                service_call_id=_SC_ID,
                technician_id=_TECH_ID,
                customer_id=_CUST_ID,
                time_range=_tr(9, 11),
            )
        assert len(calendar.created_events) == 0
        assert len(list(appt_repo._store)) == 0
        assert len(outbox.all_entries) == 0

    def test_booking_cancelled_service_call_raises_invalid_transition(
        self,
        svc: AppointmentService,
        sc_repo: InMemoryServiceCallRepository,
        appt_repo: InMemoryAppointmentRepository,
        calendar: FakeCalendarPort,
        outbox: InMemoryOutboxRepository,
    ):
        sc = ServiceCall(
            id=_SC_ID,
            customer_id=_CUST_ID,
            description="Boiler repair",
            status=ServiceCallStatus.CANCELLED,
            created_at=_FIXED_NOW,
        )
        sc_repo.add(sc)
        with pytest.raises(InvalidTransition):
            svc.book_appointment(
                service_call_id=_SC_ID,
                technician_id=_TECH_ID,
                customer_id=_CUST_ID,
                time_range=_tr(9, 11),
            )
        assert len(calendar.created_events) == 0
        assert len(list(appt_repo._store)) == 0
        assert len(outbox.all_entries) == 0


class TestBookAppointmentContactEnforcement:
    """book_appointment rejects when the contact data an appointment depends on is incomplete.

    The customer must have an address and a phone; the assigned technician must have a phone.
    """

    def _svc_with(
        self,
        contacts: dict,
        appt_repo,
        sc_repo,
        calendar,
        notifications,
        outbox,
    ) -> AppointmentService:
        return AppointmentService(
            appointments=appt_repo,
            service_calls=sc_repo,
            calendar=calendar,
            notifications=notifications,
            outbox=outbox,
            clock=lambda: _FIXED_NOW,
            new_id=lambda: _APPT_ID,
            contact_resolver=lambda uid: contacts.get(uid, ContactInfo()),
        )

    def _book(self, service):
        return service.book_appointment(
            service_call_id=_SC_ID,
            technician_id=_TECH_ID,
            customer_id=_CUST_ID,
            time_range=_tr(9, 11),
        )

    def test_rejects_when_customer_lacks_phone(
        self, appt_repo, sc_repo, calendar, notifications, outbox
    ):
        _seed_open_service_call(sc_repo)
        service = self._svc_with(
            {
                _CUST_ID: ContactInfo(address="12 Main St", phone=None),
                _TECH_ID: ContactInfo(phone="+972-50-9"),
            },
            appt_repo, sc_repo, calendar, notifications, outbox,
        )
        with pytest.raises(IncompleteContactInfo) as exc:
            self._book(service)
        assert "customer phone" in exc.value.missing

    def test_rejects_when_customer_lacks_address(
        self, appt_repo, sc_repo, calendar, notifications, outbox
    ):
        _seed_open_service_call(sc_repo)
        service = self._svc_with(
            {
                _CUST_ID: ContactInfo(address="  ", phone="+972-50-1"),
                _TECH_ID: ContactInfo(phone="+972-50-9"),
            },
            appt_repo, sc_repo, calendar, notifications, outbox,
        )
        with pytest.raises(IncompleteContactInfo) as exc:
            self._book(service)
        assert "customer address" in exc.value.missing

    def test_rejects_when_technician_lacks_phone(
        self, appt_repo, sc_repo, calendar, notifications, outbox
    ):
        _seed_open_service_call(sc_repo)
        service = self._svc_with(
            {
                _CUST_ID: ContactInfo(address="12 Main St", phone="+972-50-1"),
                _TECH_ID: ContactInfo(phone=None),
            },
            appt_repo, sc_repo, calendar, notifications, outbox,
        )
        with pytest.raises(IncompleteContactInfo) as exc:
            self._book(service)
        assert "technician phone" in exc.value.missing

    def test_rejection_happens_before_any_mutation_or_notification(
        self, appt_repo, sc_repo, calendar, notifications, outbox
    ):
        _seed_open_service_call(sc_repo)
        service = self._svc_with({}, appt_repo, sc_repo, calendar, notifications, outbox)
        with pytest.raises(IncompleteContactInfo):
            self._book(service)
        assert len(list(appt_repo._store)) == 0
        assert len(outbox.all_entries) == 0
        assert notifications.calls == []
        assert sc_repo.get(_SC_ID).status is ServiceCallStatus.OPEN

    def test_succeeds_when_all_contact_present(
        self, appt_repo, sc_repo, calendar, notifications, outbox
    ):
        _seed_open_service_call(sc_repo)
        service = self._svc_with(
            {
                _CUST_ID: ContactInfo(address="12 Main St", phone="+972-50-1"),
                _TECH_ID: ContactInfo(phone="+972-50-9"),
            },
            appt_repo, sc_repo, calendar, notifications, outbox,
        )
        appt = self._book(service)
        assert appt.status == AppointmentStatus.SCHEDULED


class TestBookingCancellationRateLimit:
    """book_appointment rejects a customer whose recent cancellations exceed the configured limit.

    The limit counts the customer's CANCELLED audit records inside a rolling window; once the
    threshold is reached, booking stays blocked until the cool-off elapses after the latest
    cancellation.
    """

    _LIMIT = CancellationRateLimit(
        max_cancellations=2,
        window=timedelta(hours=24),
        cooloff=timedelta(hours=6),
    )

    def _svc_with_limit(
        self, limit, appt_repo, sc_repo, calendar, notifications, outbox, display_tz=timezone.utc
    ) -> AppointmentService:
        return AppointmentService(
            appointments=appt_repo,
            service_calls=sc_repo,
            calendar=calendar,
            notifications=notifications,
            outbox=outbox,
            clock=lambda: _FIXED_NOW,
            new_id=lambda: _APPT_ID,
            contact_resolver=_complete_contact,
            cancellation_limit=limit,
            display_tz=display_tz,
        )

    def _seed_cancellation(self, appt_repo, occurred_at: datetime, customer_id: UUID = _CUST_ID) -> None:
        """Store a cancelled appointment so its CANCELLED audit lands in the repository log."""
        appt = Appointment(
            id=uuid4(),
            service_call_id=uuid4(),
            technician_id=_TECH_ID,
            customer_id=customer_id,
            time_range=_tr(9, 11, day=1),
            status=AppointmentStatus.SCHEDULED,
            details=None,
            created_at=occurred_at,
            updated_at=occurred_at,
        )
        appt.cancel(now=occurred_at)
        appt_repo.add(appt)

    def _book(self, service):
        return service.book_appointment(
            service_call_id=_SC_ID,
            technician_id=_TECH_ID,
            customer_id=_CUST_ID,
            time_range=_tr(9, 11),
        )

    def test_blocks_booking_at_threshold_within_window(
        self, appt_repo, sc_repo, calendar, notifications, outbox
    ):
        _seed_open_service_call(sc_repo)
        self._seed_cancellation(appt_repo, _FIXED_NOW - timedelta(hours=2))
        self._seed_cancellation(appt_repo, _FIXED_NOW - timedelta(hours=1))
        service = self._svc_with_limit(
            self._LIMIT, appt_repo, sc_repo, calendar, notifications, outbox
        )
        with pytest.raises(BookingRateLimited) as exc:
            self._book(service)
        assert exc.value.retry_at == _FIXED_NOW - timedelta(hours=1) + timedelta(hours=6)

    def test_rejection_happens_before_any_mutation_or_notification(
        self, appt_repo, sc_repo, calendar, notifications, outbox
    ):
        _seed_open_service_call(sc_repo)
        self._seed_cancellation(appt_repo, _FIXED_NOW - timedelta(hours=2))
        self._seed_cancellation(appt_repo, _FIXED_NOW - timedelta(hours=1))
        service = self._svc_with_limit(
            self._LIMIT, appt_repo, sc_repo, calendar, notifications, outbox
        )
        with pytest.raises(BookingRateLimited):
            self._book(service)
        assert _APPT_ID not in appt_repo._store
        assert len(outbox.all_entries) == 0
        assert notifications.calls == []
        assert sc_repo.get(_SC_ID).status is ServiceCallStatus.OPEN

    def test_rejection_message_renders_reopen_time_in_display_timezone(
        self, appt_repo, sc_repo, calendar, notifications, outbox
    ):
        _seed_open_service_call(sc_repo)
        self._seed_cancellation(appt_repo, _FIXED_NOW - timedelta(hours=2))
        self._seed_cancellation(appt_repo, _FIXED_NOW - timedelta(hours=1))
        service = self._svc_with_limit(
            self._LIMIT, appt_repo, sc_repo, calendar, notifications, outbox,
            display_tz=zoneinfo.ZoneInfo("Asia/Jerusalem"),
        )
        with pytest.raises(BookingRateLimited) as exc:
            self._book(service)
        # retry_at is 13:00 UTC; Asia/Jerusalem in June is UTC+3 (IDT).
        assert "16:00 IDT" in str(exc.value)
        assert exc.value.retry_at == _FIXED_NOW - timedelta(hours=1) + timedelta(hours=6)

    def test_cancellations_older_than_window_do_not_count(
        self, appt_repo, sc_repo, calendar, notifications, outbox
    ):
        _seed_open_service_call(sc_repo)
        self._seed_cancellation(appt_repo, _FIXED_NOW - timedelta(hours=30))
        self._seed_cancellation(appt_repo, _FIXED_NOW - timedelta(hours=25))
        service = self._svc_with_limit(
            self._LIMIT, appt_repo, sc_repo, calendar, notifications, outbox
        )
        appt = self._book(service)
        assert appt.status is AppointmentStatus.SCHEDULED

    def test_booking_reopens_after_cooloff(
        self, appt_repo, sc_repo, calendar, notifications, outbox
    ):
        _seed_open_service_call(sc_repo)
        self._seed_cancellation(appt_repo, _FIXED_NOW - timedelta(hours=8))
        self._seed_cancellation(appt_repo, _FIXED_NOW - timedelta(hours=7))
        service = self._svc_with_limit(
            self._LIMIT, appt_repo, sc_repo, calendar, notifications, outbox
        )
        appt = self._book(service)
        assert appt.status is AppointmentStatus.SCHEDULED

    def test_other_customers_cancellations_do_not_count(
        self, appt_repo, sc_repo, calendar, notifications, outbox
    ):
        _seed_open_service_call(sc_repo)
        other_customer = uuid4()
        self._seed_cancellation(appt_repo, _FIXED_NOW - timedelta(hours=2), other_customer)
        self._seed_cancellation(appt_repo, _FIXED_NOW - timedelta(hours=1), other_customer)
        service = self._svc_with_limit(
            self._LIMIT, appt_repo, sc_repo, calendar, notifications, outbox
        )
        appt = self._book(service)
        assert appt.status is AppointmentStatus.SCHEDULED

    def test_no_limit_configured_allows_repeated_churn(
        self, appt_repo, sc_repo, calendar, notifications, outbox, svc
    ):
        _seed_open_service_call(sc_repo)
        for hours_ago in range(1, 6):
            self._seed_cancellation(appt_repo, _FIXED_NOW - timedelta(hours=hours_ago))
        appt = self._book(svc)
        assert appt.status is AppointmentStatus.SCHEDULED


# ---------------------------------------------------------------------------
# Clock purity — mutation methods propagate clock's timestamp exactly
# ---------------------------------------------------------------------------


class TestClockPurityOnMutations:
    def _book(
        self,
        svc: AppointmentService,
        sc_repo: InMemoryServiceCallRepository,
    ) -> Appointment:
        _seed_open_service_call(sc_repo)
        return svc.book_appointment(
            service_call_id=_SC_ID,
            technician_id=_TECH_ID,
            customer_id=_CUST_ID,
            time_range=_tr(9, 11),
        )

    def test_reschedule_sets_updated_at_from_clock(
        self,
        appt_repo: InMemoryAppointmentRepository,
        sc_repo: InMemoryServiceCallRepository,
        calendar: FakeCalendarPort,
        notifications: FakeNotificationPort,
        outbox: InMemoryOutboxRepository,
    ):
        later_now = datetime(2024, 6, 10, 10, 0, tzinfo=_TZ)
        svc = AppointmentService(
            appointments=appt_repo,
            service_calls=sc_repo,
            calendar=calendar,
            notifications=notifications,
            outbox=outbox,
            clock=lambda: later_now,
            new_id=lambda: _APPT_ID,
            contact_resolver=_complete_contact,
        )
        _seed_open_service_call(sc_repo)
        appt = svc.book_appointment(
            service_call_id=_SC_ID,
            technician_id=_TECH_ID,
            customer_id=_CUST_ID,
            time_range=_tr(9, 11),
        )
        updated = svc.reschedule_appointment(appt.id, _tr(13, 15))
        assert updated.updated_at == later_now

    def test_cancel_sets_updated_at_from_clock(
        self,
        appt_repo: InMemoryAppointmentRepository,
        sc_repo: InMemoryServiceCallRepository,
        calendar: FakeCalendarPort,
        notifications: FakeNotificationPort,
        outbox: InMemoryOutboxRepository,
    ):
        later_now = datetime(2024, 6, 10, 11, 0, tzinfo=_TZ)
        svc = AppointmentService(
            appointments=appt_repo,
            service_calls=sc_repo,
            calendar=calendar,
            notifications=notifications,
            outbox=outbox,
            clock=lambda: later_now,
            new_id=lambda: _APPT_ID,
            contact_resolver=_complete_contact,
        )
        _seed_open_service_call(sc_repo)
        appt = svc.book_appointment(
            service_call_id=_SC_ID,
            technician_id=_TECH_ID,
            customer_id=_CUST_ID,
            time_range=_tr(9, 11),
        )
        cancelled = svc.cancel_appointment(appt.id)
        assert cancelled.updated_at == later_now

    def test_add_details_sets_updated_at_from_clock(
        self,
        appt_repo: InMemoryAppointmentRepository,
        sc_repo: InMemoryServiceCallRepository,
        calendar: FakeCalendarPort,
        notifications: FakeNotificationPort,
        outbox: InMemoryOutboxRepository,
    ):
        later_now = datetime(2024, 6, 10, 12, 0, tzinfo=_TZ)
        svc = AppointmentService(
            appointments=appt_repo,
            service_calls=sc_repo,
            calendar=calendar,
            notifications=notifications,
            outbox=outbox,
            clock=lambda: later_now,
            new_id=lambda: _APPT_ID,
            contact_resolver=_complete_contact,
        )
        _seed_open_service_call(sc_repo)
        appt = svc.book_appointment(
            service_call_id=_SC_ID,
            technician_id=_TECH_ID,
            customer_id=_CUST_ID,
            time_range=_tr(9, 11),
        )
        updated = svc.add_details(appt.id, "Some note")
        assert updated.updated_at == later_now
