"""The in-memory fakes structurally satisfy the assist port Protocols and their stated behaviour."""
import uuid
from datetime import datetime, timezone

import pytest

from tests.assist.fakes import (
    FakeChatModel,
    FakeConversationRepository,
    FakeDocumentIndex,
    FakeKbDocumentRepository,
    FakeServiceCallOpener,
    FakeTextExtractor,
)

from fsm.assist.domain.conversation import Conversation, ConversationStatus
from fsm.assist.domain.errors import ConversationAlreadyOpen
from fsm.assist.ports.chat_model import ChatModel
from fsm.assist.ports.conversation_repository import ConversationRepository
from fsm.assist.ports.document_index import DocumentIndex
from fsm.assist.ports.document_repository import KbDocumentRepository
from fsm.assist.ports.service_calls import ServiceCallOpener
from fsm.assist.ports.text_extractor import TextExtractor

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)


def test_fakes_satisfy_the_ports():
    assert isinstance(FakeKbDocumentRepository(), KbDocumentRepository)
    assert isinstance(FakeDocumentIndex(), DocumentIndex)
    assert isinstance(FakeTextExtractor(), TextExtractor)


def test_fake_chat_model_satisfies_the_port() -> None:
    assert isinstance(FakeChatModel(), ChatModel)


def test_fake_conversation_repository_satisfies_the_port() -> None:
    assert isinstance(FakeConversationRepository(), ConversationRepository)


def test_fake_service_call_opener_satisfies_the_port() -> None:
    assert isinstance(FakeServiceCallOpener(), ServiceCallOpener)


def make_conversation(customer_id: uuid.UUID) -> Conversation:
    return Conversation(
        id=uuid.uuid4(),
        customer_id=customer_id,
        status=ConversationStatus.ACTIVE,
        created_at=NOW,
        updated_at=NOW,
    )


def test_fake_conversation_repository_rejects_a_second_open_conversation() -> None:
    repo = FakeConversationRepository()
    customer_id = uuid.uuid4()
    repo.add(make_conversation(customer_id))

    with pytest.raises(ConversationAlreadyOpen):
        repo.add(make_conversation(customer_id))


def test_fake_conversation_repository_accepts_a_closed_conversation_beside_an_open_one() -> None:
    """The partial unique index covers only ACTIVE rows; the fake must not be stricter."""
    repo = FakeConversationRepository()
    customer_id = uuid.uuid4()
    open_convo = make_conversation(customer_id)
    repo.add(open_convo)

    closed = make_conversation(customer_id)
    closed.mark_solved(NOW)
    repo.add(closed)

    assert repo.find_active_for_customer(customer_id) is open_convo
