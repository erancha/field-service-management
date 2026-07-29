"""PGVectorStore-backed index: chunk, store, search, delete, reset — with fake embeddings."""
import os
import uuid

import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding

from fsm.assist.adapters.vector_index import PgVectorDocumentIndex


@pytest.fixture()
def index(pg_engine):
    return PgVectorDocumentIndex(
        connection_url=os.environ["DATABASE_URL"],
        embeddings=DeterministicFakeEmbedding(size=64),
        table_name="kb_chunk_test",
    )


def test_index_search_and_remove_roundtrip(index):
    doc_id = uuid.uuid4()
    text = "The breaker panel is behind the garage door. " * 40  # long enough to chunk
    count = index.index_document(doc_id, "panel.txt", text)
    assert count >= 1

    hits = index.search("breaker panel", limit=3)
    assert hits and hits[0].document_id == doc_id
    assert hits[0].filename == "panel.txt"
    assert isinstance(hits[0].score, float) and hits[0].score <= 1.0

    index.remove_document(doc_id, count)
    assert index.search("breaker panel", limit=3) == []


def test_reset_drops_everything(index):
    doc_id = uuid.uuid4()
    index.index_document(doc_id, "a.txt", "alpha beta gamma")
    index.reset()
    assert index.search("alpha", limit=3) == []
