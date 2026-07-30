"""delete_service_call: remove a service call's rows and its stored photo objects together."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from fsm.assist.ports.photo_store import object_prefix, original_key, preview_key
from fsm.platform.service_call_bridge import delete_service_call
from fsm.scheduling.adapters.repositories import (
    SqlAlchemyServiceCallAttachmentRepository,
    SqlAlchemyServiceCallRepository,
)
from fsm.scheduling.domain.attachment import ServiceCallAttachment
from fsm.scheduling.domain.errors import NotFoundError
from fsm.scheduling.domain.service_call import ServiceCall, ServiceCallStatus
from tests.assist.fakes import FakePhotoStore

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def session(pg_engine):
    with Session(pg_engine) as session:
        yield session
        session.rollback()


@dataclass
class SeedRows:
    call_id: uuid.UUID
    object_key: str


@pytest.fixture
def seed_rows(session) -> SeedRows:
    """A persisted service call with one photo attachment, committed so the bridge sees it."""
    call_id = uuid.uuid4()
    photo_id = uuid.uuid4()
    object_key = object_prefix(photo_id)

    SqlAlchemyServiceCallRepository(session).add(
        ServiceCall(
            id=call_id, customer_id=uuid.uuid4(), description="Fix boiler",
            status=ServiceCallStatus.OPEN, created_at=NOW,
        )
    )
    SqlAlchemyServiceCallAttachmentRepository(session).add_all([
        ServiceCallAttachment(
            id=photo_id, service_call_id=call_id, filename="plate.jpg", media_type="image/jpeg",
            size_bytes=14, object_key=object_key, created_at=NOW,
        )
    ])
    session.commit()
    return SeedRows(call_id=call_id, object_key=object_key)


def test_delete_service_call_removes_rows_and_objects(session, seed_rows: SeedRows) -> None:
    store = FakePhotoStore()
    store.put(original_key(seed_rows.object_key), b"o", "image/jpeg")
    store.put(preview_key(seed_rows.object_key), b"p", "image/jpeg")

    delete_service_call(session, store, seed_rows.call_id)

    assert store.objects == {}
    with pytest.raises(NotFoundError):
        SqlAlchemyServiceCallRepository(session).get(seed_rows.call_id)
    assert (
        SqlAlchemyServiceCallAttachmentRepository(session).list_for_service_call(
            seed_rows.call_id
        )
        == []
    )


def test_delete_service_call_with_no_photos_removes_nothing_from_the_store(session) -> None:
    call_id = uuid.uuid4()
    SqlAlchemyServiceCallRepository(session).add(
        ServiceCall(
            id=call_id, customer_id=uuid.uuid4(), description="No photos",
            status=ServiceCallStatus.OPEN, created_at=NOW,
        )
    )
    session.commit()
    store = FakePhotoStore()

    delete_service_call(session, store, call_id)

    assert store.objects == {}
    assert store.removed == []
    with pytest.raises(NotFoundError):
        SqlAlchemyServiceCallRepository(session).get(call_id)


def test_delete_missing_service_call_raises_not_found(session) -> None:
    store = FakePhotoStore()
    with pytest.raises(NotFoundError):
        delete_service_call(session, store, uuid.uuid4())
