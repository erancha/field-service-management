"""One suite over both ServiceCallOpener implementations, so the fake stays faithful."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from fsm.assist.domain.conversation import Photo
from fsm.assist.ports.service_calls import ServiceCallOpener
from fsm.platform.service_call_bridge import SchedulingServiceCallOpener
from fsm.scheduling.adapters.repositories import (
    SqlAlchemyServiceCallAttachmentRepository,
    SqlAlchemyServiceCallRepository,
)
from fsm.scheduling.domain import ServiceCallStatus
from tests.assist.fakes import FakeServiceCallOpener

DESCRIPTION = "Equipment: Oven\nProblem category: Not heating"


@pytest.fixture
def session(pg_engine):
    with Session(pg_engine) as session:
        yield session
        session.rollback()


@pytest.fixture(params=["fake", "scheduling"])
def opener(request, session) -> ServiceCallOpener:
    if request.param == "fake":
        return FakeServiceCallOpener()
    return SchedulingServiceCallOpener(session)


def test_opener_satisfies_the_port(opener: ServiceCallOpener) -> None:
    assert isinstance(opener, ServiceCallOpener)


def test_open_returns_the_id_and_description_it_was_given(opener: ServiceCallOpener) -> None:
    opened = opener.open(uuid.uuid4(), DESCRIPTION)

    assert isinstance(opened.id, uuid.UUID)
    assert opened.description == DESCRIPTION


def test_each_call_opens_a_distinct_service_call(opener: ServiceCallOpener) -> None:
    customer_id = uuid.uuid4()

    first = opener.open(customer_id, DESCRIPTION)
    second = opener.open(customer_id, DESCRIPTION)

    assert first.id != second.id


def test_scheduling_opener_persists_an_open_service_call_for_the_customer(session) -> None:
    customer_id = uuid.uuid4()

    opened = SchedulingServiceCallOpener(session).open(customer_id, DESCRIPTION)
    session.commit()
    session.expunge_all()

    stored = SqlAlchemyServiceCallRepository(session).get(opened.id)
    assert stored.customer_id == customer_id
    assert stored.description == DESCRIPTION
    assert stored.status is ServiceCallStatus.OPEN


def test_open_accepts_photos(opener: ServiceCallOpener) -> None:
    photo = Photo(
        id=uuid.uuid4(),
        filename="plate.jpg",
        media_type="image/jpeg",
        size_bytes=10,
        object_key="photos/x",
        created_at=datetime.now(timezone.utc),
    )

    opened = opener.open(uuid.uuid4(), DESCRIPTION, photos=[photo])

    assert isinstance(opened.id, uuid.UUID)


def test_open_with_photos_persists_attachment_rows(session) -> None:
    photo = Photo(
        id=uuid.uuid4(),
        filename="plate.jpg",
        media_type="image/jpeg",
        size_bytes=10,
        object_key="photos/x",
        created_at=datetime.now(timezone.utc),
    )
    opened = SchedulingServiceCallOpener(session).open(uuid.uuid4(), DESCRIPTION, photos=[photo])
    session.commit()

    stored = SqlAlchemyServiceCallAttachmentRepository(session).list_for_service_call(opened.id)
    assert [(a.id, a.object_key) for a in stored] == [(photo.id, "photos/x")]
