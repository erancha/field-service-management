"""Pytest fixtures exposing in-memory fake implementations of assist ports."""
from __future__ import annotations

import pytest

from tests.assist.fakes import (
    FakeDocumentIndex,
    FakeKbDocumentRepository,
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
