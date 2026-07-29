"""KnowledgeBaseService: upload → extract → index, delete, search, and re-index."""
import uuid
from datetime import UTC, datetime

import pytest
from tests.assist.fakes import FakeDocumentIndex, FakeKbDocumentRepository, FakeTextExtractor

from fsm.assist.application.knowledge_base import KnowledgeBaseService
from fsm.assist.domain.errors import (
    DocumentNotFound,
    EmptyDocumentText,
    IndexModelMismatch,
    UnsupportedDocumentType,
)

MODEL = "openai:text-embedding-3-small"
NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


def make_service(model: str = MODEL):
    repo, index, extractor = FakeKbDocumentRepository(), FakeDocumentIndex(), FakeTextExtractor()
    svc = KnowledgeBaseService(
        documents=repo, index=index, extractor=extractor, embedding_model=model,
        clock=lambda: NOW,
    )
    return svc, repo, index


def test_upload_stores_and_indexes():
    svc, repo, index = make_service()
    doc = svc.upload("reset.md", "text/markdown", b"Hold the reset button", uuid.uuid4())
    assert doc.chunk_count == 1
    assert doc.embedding_model == MODEL
    assert repo.get(doc.id).chunk_count == 1
    assert index.texts[doc.id] == ("reset.md", "Hold the reset button")


def test_upload_rejects_unsupported_type():
    svc, _, _ = make_service()
    with pytest.raises(UnsupportedDocumentType):
        svc.upload("photo.png", "image/png", b"\x89PNG", uuid.uuid4())


def test_upload_rejects_empty_text():
    svc, _, _ = make_service()
    with pytest.raises(EmptyDocumentText):
        svc.upload("blank.txt", "text/plain", b"   \n", uuid.uuid4())


def test_delete_removes_row_and_chunks():
    svc, repo, index = make_service()
    doc = svc.upload("a.txt", "text/plain", b"alpha", uuid.uuid4())
    svc.delete(doc.id)
    assert repo.rows == {}
    assert index.texts == {}


def test_delete_unknown_document_raises():
    svc, _, _ = make_service()
    with pytest.raises(DocumentNotFound):
        svc.delete(uuid.uuid4())


def test_search_returns_hits():
    svc, _, _ = make_service()
    doc = svc.upload("fuse.txt", "text/plain", b"Check the fuse box first", uuid.uuid4())
    hits = svc.search("fuse")
    assert [h.document_id for h in hits] == [doc.id]


def test_search_refuses_a_stale_index():
    svc, repo, index = make_service()
    doc = svc.upload("a.txt", "text/plain", b"alpha", uuid.uuid4())
    repo.update_index_state(doc.id, 1, "openai:text-embedding-ancient")
    assert svc.needs_reindex() is True
    with pytest.raises(IndexModelMismatch):
        svc.search("alpha")


def test_reindex_rebuilds_every_document_with_the_configured_model():
    svc, repo, index = make_service()
    doc = svc.upload("a.txt", "text/plain", b"alpha", uuid.uuid4())
    repo.update_index_state(doc.id, 1, "openai:text-embedding-ancient")
    count = svc.reindex()
    assert count == 1
    assert index.reset_calls == 1
    assert repo.get(doc.id).embedding_model == MODEL
    assert svc.needs_reindex() is False
