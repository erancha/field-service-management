"""Conversation persistence against a real Postgres schema."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from fsm.assist.adapters.conversation_repository import SqlAlchemyConversationRepository
from fsm.assist.domain.conversation import (
    OPENING_LINE_CHARS,
    Conversation,
    ConversationStatus,
    Message,
    MessageRole,
)
from fsm.assist.domain.errors import ConversationAlreadyOpen, ConversationNotFound
from fsm.assist.ports.conversation_repository import ConversationRepository

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def session(pg_engine):
    with Session(pg_engine) as session:
        yield session
        session.rollback()


def make_conversation(customer_id: uuid.UUID) -> Conversation:
    return Conversation(
        id=uuid.uuid4(),
        customer_id=customer_id,
        status=ConversationStatus.ACTIVE,
        created_at=NOW,
        updated_at=NOW,
    )


def message(role: MessageRole, text: str, offset_seconds: int = 0) -> Message:
    return Message(
        id=uuid.uuid4(),
        role=role,
        text=text,
        created_at=NOW + timedelta(seconds=offset_seconds),
    )


def test_adapter_satisfies_the_port(session) -> None:
    assert isinstance(SqlAlchemyConversationRepository(session), ConversationRepository)


def test_roundtrip_preserves_messages_in_order(session) -> None:
    repo = SqlAlchemyConversationRepository(session)
    customer_id = uuid.uuid4()
    convo = make_conversation(customer_id)
    convo.append(message(MessageRole.CUSTOMER, "It will not heat.", 0), NOW)
    convo.append(message(MessageRole.ASSISTANT, "Is the display lit?", 1), NOW)
    repo.add(convo)
    session.commit()
    session.expunge_all()

    loaded = SqlAlchemyConversationRepository(session).get(convo.id, customer_id)

    assert loaded.status is ConversationStatus.ACTIVE
    assert loaded.customer_id == customer_id
    assert [(m.role, m.text) for m in loaded.messages] == [
        (MessageRole.CUSTOMER, "It will not heat."),
        (MessageRole.ASSISTANT, "Is the display lit?"),
    ]


def test_save_persists_new_messages_and_the_ending(session) -> None:
    repo = SqlAlchemyConversationRepository(session)
    customer_id = uuid.uuid4()
    convo = make_conversation(customer_id)
    repo.add(convo)
    session.commit()

    service_call_id = uuid.uuid4()
    convo.append(message(MessageRole.CUSTOMER, "Still cold.", 0), NOW)
    convo.mark_escalated(service_call_id, NOW)
    repo.save(convo)
    session.commit()
    session.expunge_all()

    loaded = SqlAlchemyConversationRepository(session).get(convo.id, customer_id)

    assert loaded.status is ConversationStatus.ESCALATED
    assert loaded.service_call_id == service_call_id
    assert [m.text for m in loaded.messages] == ["Still cold."]


def test_save_does_not_duplicate_messages_already_stored(session) -> None:
    repo = SqlAlchemyConversationRepository(session)
    customer_id = uuid.uuid4()
    convo = make_conversation(customer_id)
    convo.append(message(MessageRole.CUSTOMER, "First.", 0), NOW)
    repo.add(convo)
    session.commit()

    convo.append(message(MessageRole.ASSISTANT, "Second.", 1), NOW)
    repo.save(convo)
    session.commit()
    repo.save(convo)
    session.commit()
    session.expunge_all()

    loaded = SqlAlchemyConversationRepository(session).get(convo.id, customer_id)
    assert [m.text for m in loaded.messages] == ["First.", "Second."]


def test_get_rejects_another_customers_conversation(session) -> None:
    repo = SqlAlchemyConversationRepository(session)
    convo = make_conversation(uuid.uuid4())
    repo.add(convo)
    session.commit()

    with pytest.raises(ConversationNotFound):
        repo.get(convo.id, uuid.uuid4())


def test_get_raises_for_an_unknown_id(session) -> None:
    with pytest.raises(ConversationNotFound):
        SqlAlchemyConversationRepository(session).get(uuid.uuid4(), uuid.uuid4())


def test_save_raises_for_a_conversation_that_was_never_added(session) -> None:
    with pytest.raises(ConversationNotFound):
        SqlAlchemyConversationRepository(session).save(make_conversation(uuid.uuid4()))


def test_add_rejects_a_second_active_conversation_for_one_customer(session) -> None:
    repo = SqlAlchemyConversationRepository(session)
    customer_id = uuid.uuid4()
    repo.add(make_conversation(customer_id))
    session.commit()

    with pytest.raises(ConversationAlreadyOpen):
        repo.add(make_conversation(customer_id))


def test_the_session_stays_usable_after_a_rejected_second_conversation(session) -> None:
    repo = SqlAlchemyConversationRepository(session)
    customer_id = uuid.uuid4()
    winner = make_conversation(customer_id)
    repo.add(winner)
    session.commit()

    with pytest.raises(ConversationAlreadyOpen):
        repo.add(make_conversation(customer_id))

    assert repo.find_active_for_customer(customer_id).id == winner.id


def test_add_allows_a_new_conversation_once_the_previous_one_ended(session) -> None:
    repo = SqlAlchemyConversationRepository(session)
    customer_id = uuid.uuid4()
    first = make_conversation(customer_id)
    repo.add(first)
    first.mark_solved(NOW)
    repo.save(first)
    session.commit()

    second = make_conversation(customer_id)
    repo.add(second)
    session.commit()

    assert repo.find_active_for_customer(customer_id).id == second.id


def test_add_accepts_a_closed_conversation_beside_an_open_one(session) -> None:
    """The unique index is partial on ACTIVE, so an ended conversation is never in its way."""
    repo = SqlAlchemyConversationRepository(session)
    customer_id = uuid.uuid4()
    open_convo = make_conversation(customer_id)
    repo.add(open_convo)

    closed = make_conversation(customer_id)
    closed.mark_solved(NOW)
    repo.add(closed)
    session.commit()

    assert repo.find_active_for_customer(customer_id).id == open_convo.id


def test_add_does_not_constrain_conversations_of_different_customers(session) -> None:
    repo = SqlAlchemyConversationRepository(session)
    repo.add(make_conversation(uuid.uuid4()))
    repo.add(make_conversation(uuid.uuid4()))
    session.commit()


def test_find_active_returns_only_the_open_conversation(session) -> None:
    repo = SqlAlchemyConversationRepository(session)
    customer_id = uuid.uuid4()
    closed = make_conversation(customer_id)
    closed.mark_solved(NOW)
    repo.add(closed)
    open_convo = make_conversation(customer_id)
    repo.add(open_convo)
    session.commit()
    session.expunge_all()

    found = SqlAlchemyConversationRepository(session).find_active_for_customer(customer_id)

    assert found is not None
    assert found.id == open_convo.id


def test_find_active_returns_none_when_the_customer_has_no_open_conversation(session) -> None:
    assert SqlAlchemyConversationRepository(session).find_active_for_customer(uuid.uuid4()) is None


def closed_conversation(customer_id: uuid.UUID, opening: str, closed_at: datetime) -> Conversation:
    convo = make_conversation(customer_id)
    convo.append(message(MessageRole.CUSTOMER, opening, 0), NOW)
    convo.append(message(MessageRole.ASSISTANT, "Is the display lit?", 1), NOW)
    convo.mark_solved(closed_at)
    return convo


def test_list_ended_returns_closed_conversations_newest_first(session) -> None:
    repo = SqlAlchemyConversationRepository(session)
    customer_id = uuid.uuid4()
    older = closed_conversation(customer_id, "The oven will not heat.", NOW)
    newer = closed_conversation(customer_id, "The fridge is noisy.", NOW + timedelta(hours=1))
    repo.add(older)
    repo.add(newer)
    session.commit()
    session.expunge_all()

    listed = SqlAlchemyConversationRepository(session).list_ended(customer_id, limit=10)

    assert [(s.id, s.opening_line) for s in listed] == [
        (newer.id, "The fridge is noisy."),
        (older.id, "The oven will not heat."),
    ]
    assert listed[0].status is ConversationStatus.SOLVED


def test_list_ended_omits_the_open_conversation(session) -> None:
    repo = SqlAlchemyConversationRepository(session)
    customer_id = uuid.uuid4()
    still_open = make_conversation(customer_id)
    still_open.append(message(MessageRole.CUSTOMER, "It is still cold.", 0), NOW)
    repo.add(still_open)
    session.commit()

    assert repo.list_ended(customer_id, limit=10) == []


def test_list_ended_omits_a_conversation_nobody_typed_into(session) -> None:
    """Opening the chat inserts a row before the customer says anything; a closed empty one is
    not an exchange the customer could recognise in a list."""
    repo = SqlAlchemyConversationRepository(session)
    customer_id = uuid.uuid4()
    never_used = make_conversation(customer_id)
    never_used.mark_abandoned(NOW)
    repo.add(never_used)
    session.commit()

    assert repo.list_ended(customer_id, limit=10) == []


def test_list_ended_shortens_a_long_opening_line(session) -> None:
    repo = SqlAlchemyConversationRepository(session)
    customer_id = uuid.uuid4()
    repo.add(closed_conversation(customer_id, "cold " * 200, NOW))
    session.commit()

    listed = repo.list_ended(customer_id, limit=10)

    assert listed[0].opening_line == ("cold " * 200)[:OPENING_LINE_CHARS]


def test_list_ended_honours_the_limit_over_the_newest_conversations(session) -> None:
    repo = SqlAlchemyConversationRepository(session)
    customer_id = uuid.uuid4()
    repo.add(closed_conversation(customer_id, "First.", NOW))
    newest = closed_conversation(customer_id, "Second.", NOW + timedelta(hours=1))
    repo.add(newest)
    session.commit()

    assert [s.id for s in repo.list_ended(customer_id, limit=1)] == [newest.id]


def test_list_ended_is_scoped_to_one_customer(session) -> None:
    repo = SqlAlchemyConversationRepository(session)
    customer_id = uuid.uuid4()
    repo.add(closed_conversation(customer_id, "Mine.", NOW))
    repo.add(closed_conversation(uuid.uuid4(), "Someone else's.", NOW))
    session.commit()

    assert [s.opening_line for s in repo.list_ended(customer_id, limit=10)] == ["Mine."]
