"""Pytest fixtures exposing in-memory fake implementations of assist ports."""
from __future__ import annotations

import pytest

from tests.assist.fakes import (
    FakeChatModel,
    FakeConversationRepository,
    FakeDocumentIndex,
    FakeKbDocumentRepository,
    FakeServiceCallOpener,
    FakeTextExtractor,
)


@pytest.fixture
def fake_document_repo() -> FakeKbDocumentRepository:
    return FakeKbDocumentRepository()


@pytest.fixture
def fake_document_index() -> FakeDocumentIndex:
    return FakeDocumentIndex()


@pytest.fixture
def fake_text_extractor() -> FakeTextExtractor:
    return FakeTextExtractor()


@pytest.fixture
def fake_chat_model() -> FakeChatModel:
    return FakeChatModel()


@pytest.fixture
def fake_conversation_repo() -> FakeConversationRepository:
    return FakeConversationRepository()


@pytest.fixture
def fake_service_call_opener() -> FakeServiceCallOpener:
    return FakeServiceCallOpener()
