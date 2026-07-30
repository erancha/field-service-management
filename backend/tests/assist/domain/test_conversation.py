"""Conversation lifecycle rules for the triage chat."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from fsm.assist.domain.conversation import (
    CONVERSATION_TTL,
    Conversation,
    ConversationStatus,
    Message,
    MessageRole,
)
from fsm.assist.domain.errors import ConversationClosed

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)
CUSTOMER = uuid.uuid4()


def make_conversation(status: ConversationStatus = ConversationStatus.ACTIVE) -> Conversation:
    return Conversation(
        id=uuid.uuid4(),
        customer_id=CUSTOMER,
        status=status,
        created_at=NOW,
        updated_at=NOW,
        messages=[],
    )


def make_message(role: MessageRole, text: str) -> Message:
    return Message(id=uuid.uuid4(), role=role, text=text, created_at=NOW)


def test_appending_a_message_records_it_and_advances_updated_at() -> None:
    convo = make_conversation()
    later = NOW + timedelta(minutes=5)

    convo.append(make_message(MessageRole.CUSTOMER, "The oven will not heat."), now=later)

    assert [m.text for m in convo.messages] == ["The oven will not heat."]
    assert convo.updated_at == later


def test_appending_to_a_closed_conversation_is_rejected() -> None:
    convo = make_conversation(ConversationStatus.SOLVED)

    with pytest.raises(ConversationClosed):
        convo.append(make_message(MessageRole.CUSTOMER, "hello"), now=NOW)


def test_mark_solved_closes_the_conversation() -> None:
    convo = make_conversation()

    convo.mark_solved(now=NOW)

    assert convo.status is ConversationStatus.SOLVED
    assert convo.is_open() is False


def test_mark_escalated_records_the_service_call() -> None:
    convo = make_conversation()
    service_call_id = uuid.uuid4()

    convo.mark_escalated(service_call_id, now=NOW)

    assert convo.status is ConversationStatus.ESCALATED
    assert convo.service_call_id == service_call_id


def test_mark_abandoned_closes_the_conversation() -> None:
    convo = make_conversation()

    convo.mark_abandoned(now=NOW)

    assert convo.status is ConversationStatus.ABANDONED


def test_closing_an_already_closed_conversation_is_rejected() -> None:
    convo = make_conversation(ConversationStatus.ESCALATED)

    with pytest.raises(ConversationClosed):
        convo.mark_solved(now=NOW)


def test_conversation_expires_after_the_ttl_of_inactivity() -> None:
    convo = make_conversation()

    assert convo.is_expired(now=NOW + CONVERSATION_TTL - timedelta(seconds=1)) is False
    assert convo.is_expired(now=NOW + CONVERSATION_TTL + timedelta(seconds=1)) is True


def test_a_closed_conversation_is_never_reported_as_expired() -> None:
    convo = make_conversation(ConversationStatus.SOLVED)

    assert convo.is_expired(now=NOW + CONVERSATION_TTL * 10) is False


def test_ttl_is_twenty_four_hours() -> None:
    assert CONVERSATION_TTL == timedelta(hours=24)


def test_a_message_defaults_to_no_photos() -> None:
    message = Message(id=uuid.uuid4(), role=MessageRole.CUSTOMER, text="Hi", created_at=NOW)
    assert message.photos == ()


def test_a_message_carries_its_photos() -> None:
    from fsm.assist.domain.conversation import Photo

    photo = Photo(
        id=uuid.uuid4(),
        filename="plate.jpg",
        media_type="image/jpeg",
        size_bytes=1234,
        object_key="photos/abc",
        created_at=NOW,
    )
    message = Message(
        id=uuid.uuid4(), role=MessageRole.CUSTOMER, text="Here", created_at=NOW, photos=(photo,)
    )
    assert message.photos == (photo,)
