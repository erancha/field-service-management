"""Unit tests for ReconciliationService using in-memory fakes."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from fsm.scheduling.application.reconciliation_service import ReconciliationService
from fsm.scheduling.domain.appointment import Appointment, AppointmentStatus
from fsm.scheduling.domain.availability import AvailabilityInputs
from fsm.scheduling.domain.time_range import TimeRange
from fsm.scheduling.domain.working_hours import DailyHours, WeeklyWorkingHours
from fsm.scheduling.ports.inbound import InboundEventChange
from fsm.scheduling.ports.outbox import OutboxOperation
from tests.scheduling.fakes import (
    FakeNotificationPort,
    InMemoryAppointmentRepository,
    InMemoryOutboxRepository,
)

_TZ = timezone.utc
_BASE = datetime(2024, 6, 10, 8, 0, tzinfo=_TZ)
_TECH_ID = UUID("cccccccc-0000-0000-0000-000000000001")
_CUST_ID = UUID("dddddddd-0000-0000-0000-000000000001")
_SC_ID = UUID("bbbbbbbb-0000-0000-0000-000000000001")

_DEFAULT_RANGE = TimeRange(
    start=datetime(2024, 6, 10, 9, 0, tzinfo=_TZ),
    end=datetime(2024, 6, 10, 11, 0, tzinfo=_TZ),
)


def _make_appointment(
    appt_id: UUID | None = None,
    time_range: TimeRange = _DEFAULT_RANGE,
    status: AppointmentStatus = AppointmentStatus.SCHEDULED,
    details: str | None = None,
    updated_at: datetime = _BASE,
) -> Appointment:
    aid = appt_id or uuid4()
    return Appointment(
        id=aid,
        service_call_id=_SC_ID,
        technician_id=_TECH_ID,
        customer_id=_CUST_ID,
        time_range=time_range,
        status=status,
        details=details,
        created_at=_BASE,
        updated_at=updated_at,
    )


@pytest.fixture
def appt_repo() -> InMemoryAppointmentRepository:
    return InMemoryAppointmentRepository()


@pytest.fixture
def outbox() -> InMemoryOutboxRepository:
    return InMemoryOutboxRepository()


@pytest.fixture
def notifications() -> FakeNotificationPort:
    return FakeNotificationPort()


@pytest.fixture
def clock_time() -> datetime:
    return _BASE + timedelta(minutes=30)


def _permissive_inputs(technician_id: UUID, proposed_start: datetime) -> AvailabilityInputs:
    """Every weekday 00:00-23:59, no exclusions — isolates tests from the hours policy."""
    all_day = tuple(
        DailyHours(weekday=wd, start=time(0, 0), end=time(23, 59)) for wd in range(7)
    )
    return AvailabilityInputs(
        working_hours=WeeklyWorkingHours(windows=all_day),
        tz=timezone.utc,
        excluded_dates=frozenset(),
    )


@pytest.fixture
def svc(
    appt_repo: InMemoryAppointmentRepository,
    outbox: InMemoryOutboxRepository,
    notifications: FakeNotificationPort,
    clock_time: datetime,
) -> ReconciliationService:
    return ReconciliationService(
        appointments=appt_repo,
        outbox=outbox,
        notifications=notifications,
        availability_inputs=_permissive_inputs,
        clock=lambda: clock_time,
    )


class TestInboundReschedule:
    def test_reschedule_to_free_slot_updates_appointment_and_notifies(
        self,
        svc: ReconciliationService,
        appt_repo: InMemoryAppointmentRepository,
        outbox: InMemoryOutboxRepository,
        notifications: FakeNotificationPort,
    ) -> None:
        appt = _make_appointment()
        appt_repo.add(appt)

        new_range = TimeRange(
            start=datetime(2024, 6, 10, 13, 0, tzinfo=_TZ),
            end=datetime(2024, 6, 10, 15, 0, tzinfo=_TZ),
        )
        change = InboundEventChange(
            appointment_id=appt.id,
            cancelled=False,
            new_time_range=new_range,
            updated_at=_BASE + timedelta(hours=1),
        )

        svc.reconcile(change)

        saved = appt_repo.get(appt.id)
        assert saved.time_range == new_range
        assert saved.status == AppointmentStatus.RESCHEDULED
        assert len(notifications.calls) == 1
        assert notifications.calls[0][0] == "rescheduled"
        assert len(outbox.all_entries) == 0


class TestInboundCancel:
    def test_cancel_marks_cancelled_and_notifies(
        self,
        svc: ReconciliationService,
        appt_repo: InMemoryAppointmentRepository,
        outbox: InMemoryOutboxRepository,
        notifications: FakeNotificationPort,
    ) -> None:
        appt = _make_appointment()
        appt_repo.add(appt)

        change = InboundEventChange(
            appointment_id=appt.id,
            cancelled=True,
            new_time_range=None,
            updated_at=_BASE + timedelta(hours=1),
        )

        svc.reconcile(change)

        saved = appt_repo.get(appt.id)
        assert saved.status == AppointmentStatus.CANCELLED
        assert len(notifications.calls) == 1
        assert notifications.calls[0][0] == "cancelled"
        assert len(outbox.all_entries) == 0


class TestStaleInboundEdit:
    def test_stale_edit_causes_no_mutation_or_notification(
        self,
        svc: ReconciliationService,
        appt_repo: InMemoryAppointmentRepository,
        outbox: InMemoryOutboxRepository,
        notifications: FakeNotificationPort,
    ) -> None:
        appt = _make_appointment(updated_at=_BASE)
        appt_repo.add(appt)

        new_range = TimeRange(
            start=datetime(2024, 6, 10, 13, 0, tzinfo=_TZ),
            end=datetime(2024, 6, 10, 15, 0, tzinfo=_TZ),
        )
        # updated_at equal to appt.updated_at — stale by LWW rule
        change = InboundEventChange(
            appointment_id=appt.id,
            cancelled=False,
            new_time_range=new_range,
            updated_at=_BASE,
        )

        svc.reconcile(change)

        saved = appt_repo.get(appt.id)
        assert saved.time_range == _DEFAULT_RANGE
        assert saved.status == AppointmentStatus.SCHEDULED
        assert len(notifications.calls) == 0
        assert len(outbox.all_entries) == 0

    def test_older_edit_causes_no_mutation_or_notification(
        self,
        svc: ReconciliationService,
        appt_repo: InMemoryAppointmentRepository,
        outbox: InMemoryOutboxRepository,
        notifications: FakeNotificationPort,
    ) -> None:
        appt = _make_appointment(updated_at=_BASE)
        appt_repo.add(appt)

        change = InboundEventChange(
            appointment_id=appt.id,
            cancelled=False,
            new_time_range=None,
            updated_at=_BASE - timedelta(seconds=1),
        )

        svc.reconcile(change)

        assert len(notifications.calls) == 0
        assert len(outbox.all_entries) == 0


class TestOverlapDBWins:
    def test_overlapping_reschedule_enqueues_update_and_no_notification(
        self,
        svc: ReconciliationService,
        appt_repo: InMemoryAppointmentRepository,
        outbox: InMemoryOutboxRepository,
        notifications: FakeNotificationPort,
    ) -> None:
        appt = _make_appointment()
        appt_repo.add(appt)

        # A second appointment occupying the inbound target range
        blocking_range = TimeRange(
            start=datetime(2024, 6, 10, 13, 0, tzinfo=_TZ),
            end=datetime(2024, 6, 10, 15, 0, tzinfo=_TZ),
        )
        blocker = _make_appointment(
            appt_id=uuid4(),
            time_range=blocking_range,
        )
        appt_repo.add(blocker)

        change = InboundEventChange(
            appointment_id=appt.id,
            cancelled=False,
            new_time_range=blocking_range,
            updated_at=_BASE + timedelta(hours=1),
        )

        svc.reconcile(change)

        saved = appt_repo.get(appt.id)
        assert saved.time_range == _DEFAULT_RANGE
        assert saved.status == AppointmentStatus.SCHEDULED
        assert len(notifications.calls) == 1
        pending = outbox.pending_entries
        assert len(pending) == 1
        assert pending[0].operation == OutboxOperation.UPDATE
        assert pending[0].appointment_id == appt.id
        assert ("reschedule_rejected", appt) in notifications.calls


class TestEchoNoOp:
    def test_echo_with_matching_time_and_newer_timestamp_is_noop(
        self,
        svc: ReconciliationService,
        appt_repo: InMemoryAppointmentRepository,
        outbox: InMemoryOutboxRepository,
        notifications: FakeNotificationPort,
    ) -> None:
        appt = _make_appointment(details="existing note")
        appt_repo.add(appt)

        # Same time range as the DB row, newer updated_at: a projection echo. The event
        # description Google stamps newer is not reconciled, so nothing mutates.
        change = InboundEventChange(
            appointment_id=appt.id,
            cancelled=False,
            new_time_range=_DEFAULT_RANGE,
            updated_at=_BASE + timedelta(hours=1),
        )

        svc.reconcile(change)

        saved = appt_repo.get(appt.id)
        assert saved.time_range == _DEFAULT_RANGE
        assert saved.details == "existing note"
        assert saved.status == AppointmentStatus.SCHEDULED
        assert len(notifications.calls) == 0
        assert len(outbox.all_entries) == 0


class TestEchoDoesNotBlockLaterDrag:
    def test_drag_after_a_projection_echo_reschedules_and_notifies(
        self,
        svc: ReconciliationService,
        appt_repo: InMemoryAppointmentRepository,
        notifications: FakeNotificationPort,
    ) -> None:
        # A projection echo must leave updated_at untouched so it cannot advance the
        # last-write-wins floor past a subsequent technician drag. Reflecting the echo as a
        # details edit (the prior bug) bumped updated_at to wall-clock time and could silently
        # drop the drag, so neither the DB nor the customer notification saw the reschedule.
        appt = _make_appointment(details="existing note", updated_at=_BASE)
        appt_repo.add(appt)

        echo = InboundEventChange(
            appointment_id=appt.id,
            cancelled=False,
            new_time_range=_DEFAULT_RANGE,
            updated_at=_BASE + timedelta(hours=1),
        )
        svc.reconcile(echo)

        dragged_range = TimeRange(
            start=datetime(2024, 6, 10, 13, 0, tzinfo=_TZ),
            end=datetime(2024, 6, 10, 15, 0, tzinfo=_TZ),
        )
        drag = InboundEventChange(
            appointment_id=appt.id,
            cancelled=False,
            new_time_range=dragged_range,
            updated_at=_BASE + timedelta(hours=2),
        )
        svc.reconcile(drag)

        saved = appt_repo.get(appt.id)
        assert saved.time_range == dragged_range
        assert saved.status == AppointmentStatus.RESCHEDULED
        assert [c[0] for c in notifications.calls] == ["rescheduled"]


class TestDescriptionOnlyEditIgnored:
    def test_description_edit_without_time_change_leaves_details_unchanged(
        self,
        svc: ReconciliationService,
        appt_repo: InMemoryAppointmentRepository,
        outbox: InMemoryOutboxRepository,
        notifications: FakeNotificationPort,
    ) -> None:
        # The projected event description is a rendered composition (problem + details +
        # phone), not the raw details. An inbound change carrying no time or cancellation
        # signal — whether a genuine description edit or a projection echo — must never
        # overwrite appt.details, which previously compounded on every re-projection.
        appt = _make_appointment(details="Leaking pipe under sink")
        appt_repo.add(appt)

        change = InboundEventChange(
            appointment_id=appt.id,
            cancelled=False,
            new_time_range=None,
            updated_at=_BASE + timedelta(hours=1),
        )

        svc.reconcile(change)

        saved = appt_repo.get(appt.id)
        assert saved.details == "Leaking pipe under sink"
        assert saved.status == AppointmentStatus.SCHEDULED
        assert len(notifications.calls) == 0
        assert len(outbox.all_entries) == 0


class TestUnknownAppointment:
    def test_unknown_appointment_id_is_swallowed(
        self,
        svc: ReconciliationService,
        notifications: FakeNotificationPort,
        outbox: InMemoryOutboxRepository,
    ) -> None:
        change = InboundEventChange(
            appointment_id=uuid4(),
            cancelled=False,
            new_time_range=None,
            updated_at=_BASE + timedelta(hours=1),
        )

        # Must not raise
        svc.reconcile(change)

        assert len(notifications.calls) == 0
        assert len(outbox.all_entries) == 0


class TestAlreadyCancelled:
    def test_change_against_cancelled_appointment_is_noop(
        self,
        svc: ReconciliationService,
        appt_repo: InMemoryAppointmentRepository,
        outbox: InMemoryOutboxRepository,
        notifications: FakeNotificationPort,
    ) -> None:
        appt = _make_appointment(status=AppointmentStatus.CANCELLED)
        appt_repo.add(appt)

        new_range = TimeRange(
            start=datetime(2024, 6, 10, 13, 0, tzinfo=_TZ),
            end=datetime(2024, 6, 10, 15, 0, tzinfo=_TZ),
        )
        change = InboundEventChange(
            appointment_id=appt.id,
            cancelled=False,
            new_time_range=new_range,
            updated_at=_BASE + timedelta(hours=1),
        )

        # Must not raise
        svc.reconcile(change)

        saved = appt_repo.get(appt.id)
        assert saved.status == AppointmentStatus.CANCELLED
        assert len(notifications.calls) == 0
        assert len(outbox.all_entries) == 0


def _change(
    appt: Appointment,
    *,
    cancelled: bool = False,
    new_time_range: TimeRange | None = None,
    customer_declined: bool = False,
    updated_at: datetime | None = None,
) -> InboundEventChange:
    return InboundEventChange(
        appointment_id=appt.id,
        cancelled=cancelled,
        new_time_range=new_time_range,
        updated_at=updated_at or (_BASE + timedelta(minutes=5)),
        customer_declined=customer_declined,
    )


class TestCustomerDecline:
    def test_decline_cancels_deletes_event_and_notifies(self, svc, appt_repo, outbox, notifications):
        appt = _make_appointment()
        appt.external_event_id = "evt-1"
        appt_repo.add(appt)

        svc.reconcile(_change(appt, customer_declined=True))

        assert appt_repo.get(appt.id).status is AppointmentStatus.CANCELLED
        [entry] = outbox.entries
        assert entry.operation is OutboxOperation.DELETE
        assert entry.external_event_id == "evt-1"
        assert ("cancelled", appt) in notifications.calls

    def test_decline_wins_over_simultaneous_time_change(self, svc, appt_repo, outbox, notifications):
        appt = _make_appointment()
        appt_repo.add(appt)
        moved = TimeRange(
            start=_DEFAULT_RANGE.start + timedelta(hours=3),
            end=_DEFAULT_RANGE.end + timedelta(hours=3),
        )

        svc.reconcile(_change(appt, customer_declined=True, new_time_range=moved))

        assert appt_repo.get(appt.id).status is AppointmentStatus.CANCELLED
        assert all(kind != "rescheduled" for kind, _ in notifications.calls)

    def test_stale_decline_is_discarded(self, svc, appt_repo, outbox, notifications):
        appt = _make_appointment(updated_at=_BASE + timedelta(hours=1))
        appt_repo.add(appt)

        svc.reconcile(_change(appt, customer_declined=True, updated_at=_BASE))

        assert appt_repo.get(appt.id).status is AppointmentStatus.SCHEDULED
        assert outbox.entries == []
        assert notifications.calls == []

    def test_decline_of_cancelled_appointment_is_noop(self, svc, appt_repo, outbox, notifications):
        appt = _make_appointment(status=AppointmentStatus.CANCELLED)
        appt_repo.add(appt)

        svc.reconcile(_change(appt, customer_declined=True))

        assert outbox.entries == []
        assert notifications.calls == []


class TestBookingPolicyValidation:
    def _svc_with_hours(self, appt_repo, outbox, notifications, clock_time):
        """Service whose availability inputs are the real default schedule (Sun-Thu 9-17 UTC)."""
        def _inputs(technician_id: UUID, proposed_start: datetime) -> AvailabilityInputs:
            return AvailabilityInputs(
                working_hours=WeeklyWorkingHours.default(),
                tz=timezone.utc,
                excluded_dates=frozenset(),
            )

        return ReconciliationService(
            appt_repo, outbox, notifications,
            availability_inputs=_inputs,
            clock=lambda: clock_time,
        )

    def test_out_of_hours_move_reverts_and_notifies(self, appt_repo, outbox, notifications, clock_time):
        svc = self._svc_with_hours(appt_repo, outbox, notifications, clock_time)
        appt = _make_appointment()
        appt_repo.add(appt)
        evening = TimeRange(
            start=datetime(2024, 6, 10, 18, 0, tzinfo=_TZ),
            end=datetime(2024, 6, 10, 20, 0, tzinfo=_TZ),
        )

        svc.reconcile(_change(appt, new_time_range=evening))

        assert appt_repo.get(appt.id).time_range == _DEFAULT_RANGE
        [entry] = outbox.entries
        assert entry.operation is OutboxOperation.UPDATE
        assert ("reschedule_rejected", appt) in notifications.calls

    def test_excluded_day_move_reverts_and_notifies(self, appt_repo, outbox, notifications, clock_time):
        def _inputs(technician_id: UUID, proposed_start: datetime) -> AvailabilityInputs:
            return AvailabilityInputs(
                working_hours=WeeklyWorkingHours.default(),
                tz=timezone.utc,
                excluded_dates=frozenset({date(2024, 6, 10)}),
            )

        svc = ReconciliationService(
            appt_repo, outbox, notifications,
            availability_inputs=_inputs,
            clock=lambda: clock_time,
        )
        appt = _make_appointment()
        appt_repo.add(appt)
        same_day = TimeRange(
            start=datetime(2024, 6, 10, 12, 0, tzinfo=_TZ),
            end=datetime(2024, 6, 10, 14, 0, tzinfo=_TZ),
        )

        svc.reconcile(_change(appt, new_time_range=same_day))

        assert appt_repo.get(appt.id).time_range == _DEFAULT_RANGE
        [entry] = outbox.entries
        assert entry.operation is OutboxOperation.UPDATE
        assert ("reschedule_rejected", appt) in notifications.calls

    def test_valid_move_reschedules(self, appt_repo, outbox, notifications, clock_time):
        svc = self._svc_with_hours(appt_repo, outbox, notifications, clock_time)
        appt = _make_appointment()
        appt_repo.add(appt)
        afternoon = TimeRange(
            start=datetime(2024, 6, 10, 14, 0, tzinfo=_TZ),
            end=datetime(2024, 6, 10, 16, 0, tzinfo=_TZ),
        )

        svc.reconcile(_change(appt, new_time_range=afternoon))

        assert appt_repo.get(appt.id).time_range == afternoon
        assert ("rescheduled", appt) in notifications.calls
