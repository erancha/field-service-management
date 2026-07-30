"""Photo metadata persistence against a real Postgres schema."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from fsm.assist.adapters.conversation_repository import SqlAlchemyConversationRepository
from fsm.assist.adapters.photo_repository import SqlAlchemyPhotoRepository
from fsm.assist.domain.conversation import (
    Conversation,
    ConversationStatus,
    Message,
    MessageRole,
    Photo,
)
from fsm.assist.domain.errors import PhotoNotFound
from fsm.assist.ports.photo_store import object_prefix

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def session(pg_engine):
    with Session(pg_engine) as session:
        yield session
        session.rollback()


def _photo(filename: str = "plate.jpg", created_at: datetime = NOW) -> Photo:
    photo_id = uuid.uuid4()
    return Photo(
        id=photo_id, filename=filename, media_type="image/jpeg", size_bytes=4,
        object_key=object_prefix(photo_id), created_at=created_at,
    )


def _stored_conversation(session, *, with_message: bool = False) -> Conversation:
    """Insert a conversation (and optionally one customer message) so photo FKs resolve."""
    convo = Conversation(
        id=uuid.uuid4(), customer_id=uuid.uuid4(), status=ConversationStatus.ACTIVE,
        created_at=NOW, updated_at=NOW,
    )
    if with_message:
        convo.append(
            Message(id=uuid.uuid4(), role=MessageRole.CUSTOMER, text="Hi", created_at=NOW), NOW
        )
    SqlAlchemyConversationRepository(session).add(convo)
    return convo


def test_get_unbound_returns_requested_photos_in_request_order(session) -> None:
    convo = _stored_conversation(session)
    repo = SqlAlchemyPhotoRepository(session)
    first, second = _photo("a.jpg"), _photo("b.jpg")
    repo.add(convo.id, first)
    repo.add(convo.id, second)

    assert [p.id for p in repo.get_unbound(convo.id, [second.id, first.id])] == [
        second.id, first.id,
    ]


def test_get_unbound_rejects_a_bound_photo(session) -> None:
    convo = _stored_conversation(session, with_message=True)
    repo = SqlAlchemyPhotoRepository(session)
    photo = _photo()
    repo.add(convo.id, photo)
    repo.bind(convo.messages[0].id, [photo.id])

    with pytest.raises(PhotoNotFound):
        repo.get_unbound(convo.id, [photo.id])


def test_get_unbound_rejects_another_conversations_photo(session) -> None:
    mine, theirs = _stored_conversation(session), _stored_conversation(session)
    repo = SqlAlchemyPhotoRepository(session)
    photo = _photo()
    repo.add(theirs.id, photo)

    with pytest.raises(PhotoNotFound):
        repo.get_unbound(mine.id, [photo.id])


def test_bind_makes_a_photo_part_of_the_message(session) -> None:
    convo = _stored_conversation(session, with_message=True)
    repo = SqlAlchemyPhotoRepository(session)
    photo = _photo()
    repo.add(convo.id, photo)

    repo.bind(convo.messages[0].id, [photo.id])

    reloaded = SqlAlchemyConversationRepository(session).get(convo.id, convo.customer_id)
    assert reloaded.messages[0].photos == (photo,)


def test_bind_orders_multiple_photos_by_created_at_not_insertion_order(session) -> None:
    """The load path orders bound photos by created_at; inserting the later one first must not
    leak insertion order into the reloaded tuple."""
    convo = _stored_conversation(session, with_message=True)
    repo = SqlAlchemyPhotoRepository(session)
    earlier = _photo("earlier.jpg", created_at=NOW)
    later = _photo("later.jpg", created_at=NOW + timedelta(minutes=5))
    repo.add(convo.id, later)
    repo.add(convo.id, earlier)
    repo.bind(convo.messages[0].id, [later.id, earlier.id])

    reloaded = SqlAlchemyConversationRepository(session).get(convo.id, convo.customer_id)

    assert reloaded.messages[0].photos == (earlier, later)


def test_delete_unbound_leaves_bound_rows(session) -> None:
    convo = _stored_conversation(session, with_message=True)
    repo = SqlAlchemyPhotoRepository(session)
    bound, loose = _photo("bound.jpg"), _photo("loose.jpg")
    repo.add(convo.id, bound)
    repo.add(convo.id, loose)
    repo.bind(convo.messages[0].id, [bound.id])

    repo.delete_unbound(convo.id)

    assert repo.count_for_conversation(convo.id) == 1
    assert repo.list_unbound(convo.id) == []


def test_get_returns_an_unbound_photo(session) -> None:
    convo = _stored_conversation(session)
    repo = SqlAlchemyPhotoRepository(session)
    photo = _photo()
    repo.add(convo.id, photo)

    assert repo.get(convo.id, photo.id) == photo


def test_get_returns_a_bound_photo(session) -> None:
    convo = _stored_conversation(session, with_message=True)
    repo = SqlAlchemyPhotoRepository(session)
    photo = _photo()
    repo.add(convo.id, photo)
    repo.bind(convo.messages[0].id, [photo.id])

    assert repo.get(convo.id, photo.id) == photo


def test_get_rejects_another_conversations_photo(session) -> None:
    mine, theirs = _stored_conversation(session), _stored_conversation(session)
    repo = SqlAlchemyPhotoRepository(session)
    photo = _photo()
    repo.add(theirs.id, photo)

    with pytest.raises(PhotoNotFound):
        repo.get(mine.id, photo.id)


def test_delete_removes_exactly_the_one_row(session) -> None:
    convo = _stored_conversation(session)
    repo = SqlAlchemyPhotoRepository(session)
    doomed, spared = _photo("doomed.jpg"), _photo("spared.jpg")
    repo.add(convo.id, doomed)
    repo.add(convo.id, spared)

    repo.delete(doomed.id)

    assert repo.count_for_conversation(convo.id) == 1
    with pytest.raises(PhotoNotFound):
        repo.get(convo.id, doomed.id)
