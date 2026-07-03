"""Unit tests for ReconciliationService using in-memory fakes."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from fsm.scheduling.application.reconciliation_service import ReconciliationService
from fsm.scheduling.domain.appointment import Appointment, AppointmentStatus
from fsm.scheduling.domain.time_range import TimeRange
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
        assert len(notifications.calls) == 0
        pending = outbox.pending_entries
        assert len(pending) == 1
        assert pending[0].operation == OutboxOperation.UPDATE
        assert pending[0].appointment_id == appt.id


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
