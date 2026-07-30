"""PhotoService behavior over the in-memory fakes."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from fsm.assist.application.photos import PhotoService
from fsm.assist.domain.conversation import Conversation, ConversationStatus
from fsm.assist.domain.errors import (
    ConversationClosed,
    ConversationNotFound,
    PhotoLimitReached,
    PhotoNotFound,
)
from fsm.assist.ports.photo_store import object_prefix, original_key, preview_key

NOW = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
CUSTOMER = uuid.uuid4()


@pytest.fixture
def conversation(fake_conversation_repo) -> Conversation:
    convo = Conversation(
        id=uuid.uuid4(), customer_id=CUSTOMER, status=ConversationStatus.ACTIVE,
        created_at=NOW, updated_at=NOW,
    )
    fake_conversation_repo.add(convo)
    return convo


@pytest.fixture
def service(fake_conversation_repo, fake_photo_repo, fake_photo_store, fake_preview_maker):
    return PhotoService(
        conversations=fake_conversation_repo,
        photos=fake_photo_repo,
        photo_store=fake_photo_store,
        preview_maker=fake_preview_maker,
        clock=lambda: NOW,
    )


def test_attach_stores_the_original_the_preview_and_the_row(
    service, conversation, fake_photo_store, fake_photo_repo
) -> None:
    photo = service.attach(conversation.id, CUSTOMER, "plate.jpg", b"jpeg")

    assert photo.media_type == "image/jpeg"
    assert photo.size_bytes == 4
    assert photo.object_key == object_prefix(photo.id)
    assert fake_photo_store.objects[original_key(photo.object_key)] == (b"jpeg", "image/jpeg")
    assert fake_photo_store.objects[preview_key(photo.object_key)] == (
        b"preview:jpeg", "image/jpeg",
    )
    assert fake_photo_repo.count_for_conversation(conversation.id) == 1


def test_attach_rejects_the_sixth_photo(service, conversation) -> None:
    for n in range(5):
        service.attach(conversation.id, CUSTOMER, f"{n}.jpg", b"jpeg")

    with pytest.raises(PhotoLimitReached):
        service.attach(conversation.id, CUSTOMER, "six.jpg", b"jpeg")


def test_attach_rejects_a_closed_conversation(service, conversation, fake_conversation_repo) -> None:
    conversation.mark_abandoned(NOW)
    fake_conversation_repo.save(conversation)

    with pytest.raises(ConversationClosed):
        service.attach(conversation.id, CUSTOMER, "late.jpg", b"jpeg")


def test_attach_rejects_a_foreign_conversation(service, conversation) -> None:
    with pytest.raises(ConversationNotFound):
        service.attach(conversation.id, uuid.uuid4(), "spoof.jpg", b"jpeg")


def test_detach_removes_the_objects_the_row_and_the_count(
    service, conversation, fake_photo_store, fake_photo_repo
) -> None:
    photo = service.attach(conversation.id, CUSTOMER, "plate.jpg", b"jpeg")

    service.detach(conversation.id, CUSTOMER, photo.id)

    assert original_key(photo.object_key) not in fake_photo_store.objects
    assert preview_key(photo.object_key) not in fake_photo_store.objects
    assert fake_photo_repo.count_for_conversation(conversation.id) == 0


def test_detach_rejects_a_bound_photo(service, conversation, fake_photo_repo) -> None:
    photo = service.attach(conversation.id, CUSTOMER, "plate.jpg", b"jpeg")
    fake_photo_repo.bind(uuid.uuid4(), [photo.id])

    with pytest.raises(PhotoNotFound):
        service.detach(conversation.id, CUSTOMER, photo.id)


def test_detach_rejects_a_foreign_conversation(service, conversation) -> None:
    photo = service.attach(conversation.id, CUSTOMER, "plate.jpg", b"jpeg")

    with pytest.raises(ConversationNotFound):
        service.detach(conversation.id, uuid.uuid4(), photo.id)
