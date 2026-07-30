"""Service-call attachment persistence against a real Postgres schema."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from fsm.scheduling.adapters.repositories import (
    SqlAlchemyAppointmentRepository,
    SqlAlchemyServiceCallAttachmentRepository,
    SqlAlchemyServiceCallRepository,
)
from fsm.scheduling.domain.appointment import Appointment, AppointmentStatus
from fsm.scheduling.domain.attachment import ServiceCallAttachment
from fsm.scheduling.domain.errors import NotFoundError
from fsm.scheduling.domain.service_call import ServiceCall, ServiceCallStatus
from fsm.scheduling.domain.time_range import TimeRange

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def session(pg_engine):
    with Session(pg_engine) as session:
        yield session
        session.rollback()


def _stored_call(session) -> ServiceCall:
    call = ServiceCall(
        id=uuid.uuid4(),
        customer_id=uuid.uuid4(),
        description="Fix boiler",
        status=ServiceCallStatus.OPEN,
        created_at=NOW,
    )
    SqlAlchemyServiceCallRepository(session).add(call)
    return call


def _attachment(
    call_id: uuid.UUID, filename: str = "plate.jpg", created_at: datetime = NOW
) -> ServiceCallAttachment:
    attachment_id = uuid.uuid4()
    return ServiceCallAttachment(
        id=attachment_id,
        service_call_id=call_id,
        filename=filename,
        media_type="image/jpeg",
        size_bytes=4,
        object_key=f"photos/{attachment_id}",
        created_at=created_at,
    )


def test_add_all_then_list_for_service_call_round_trips_ordering_by_id_on_a_tie(
    session,
) -> None:
    """Same created_at for both rows means the (created_at, id) ORDER BY falls back to id;
    this exercises that tie-break explicitly."""
    call = _stored_call(session)
    repo = SqlAlchemyServiceCallAttachmentRepository(session)
    attachments = [_attachment(call.id), _attachment(call.id)]

    repo.add_all(attachments)

    assert repo.list_for_service_call(call.id) == sorted(
        attachments, key=lambda a: (a.created_at, a.id)
    )


def test_list_for_service_call_orders_by_created_at_not_insertion_order(session) -> None:
    call = _stored_call(session)
    repo = SqlAlchemyServiceCallAttachmentRepository(session)
    later = _attachment(call.id, "later.jpg", created_at=NOW + timedelta(minutes=5))
    earlier = _attachment(call.id, "earlier.jpg", created_at=NOW)

    repo.add_all([later, earlier])

    assert repo.list_for_service_call(call.id) == [earlier, later]


def test_get_raises_not_found_for_unknown_id(session) -> None:
    with pytest.raises(NotFoundError):
        SqlAlchemyServiceCallAttachmentRepository(session).get(uuid.uuid4())


def test_removing_the_service_call_cascades_to_attachments(session) -> None:
    call = _stored_call(session)
    repo = SqlAlchemyServiceCallAttachmentRepository(session)
    repo.add_all([_attachment(call.id)])

    SqlAlchemyServiceCallRepository(session).remove(call.id)

    assert repo.list_for_service_call(call.id) == []


def test_list_for_service_call_returns_that_calls_appointments(session) -> None:
    def _appointment(service_call_id: uuid.UUID, hour: int) -> Appointment:
        return Appointment(
            id=uuid.uuid4(),
            service_call_id=service_call_id,
            technician_id=uuid.uuid4(),
            customer_id=uuid.uuid4(),
            time_range=TimeRange(
                start=NOW.replace(hour=hour), end=NOW.replace(hour=hour + 1)
            ),
            status=AppointmentStatus.SCHEDULED,
            details=None,
            created_at=NOW,
            updated_at=NOW,
        )

    call = _stored_call(session)
    other_call = _stored_call(session)
    appt_repo = SqlAlchemyAppointmentRepository(session)
    first = _appointment(call.id, 9)
    second = _appointment(call.id, 11)
    elsewhere = _appointment(other_call.id, 13)
    appt_repo.add(first)
    appt_repo.add(second)
    appt_repo.add(elsewhere)

    assert {a.id for a in appt_repo.list_for_service_call(call.id)} == {first.id, second.id}
