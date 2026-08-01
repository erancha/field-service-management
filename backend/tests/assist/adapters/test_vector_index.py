"""PGVectorStore-backed index: chunk, store, search, delete, reset — with fake embeddings."""
import os
import uuid

from fsm.assist.domain.document import ExtractedText

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
    count = index.index_document(doc_id, "panel.txt", ExtractedText(text=text))
    assert count >= 1

    hits = index.search("breaker panel", limit=3)
    assert hits and hits[0].document_id == doc_id
    assert hits[0].filename == "panel.txt"
    assert isinstance(hits[0].score, float) and hits[0].score <= 1.0

    index.remove_document(doc_id, count)
    assert index.search("breaker panel", limit=3) == []


def test_index_document_reports_progress_up_to_the_chunk_total(index):
    """Progress opens with (0, total) before the first batch, then arrives batchwise,
    ending exactly at the returned chunk count."""
    doc_id = uuid.uuid4()
    text = "The breaker panel is behind the garage door. " * 400  # many chunks
    reported: list[tuple[int, int]] = []

    count = index.index_document(
        doc_id, "panel.txt", ExtractedText(text=text), on_progress=lambda done, total: reported.append((done, total))
    )

    assert count > 1
    assert reported[0] == (0, count)
    assert {total for _, total in reported} == {count}
    assert [done for done, _ in reported] == sorted(done for done, _ in reported)
    assert reported[-1][0] == count


def test_a_small_document_still_reports_stepwise_progress(index):
    """The write batch adapts downward so a short document gets a moving bar, not one 100% jump."""
    doc_id = uuid.uuid4()
    text = "The breaker panel is behind the garage door. " * 100  # a handful of chunks
    reported: list[tuple[int, int]] = []

    count = index.index_document(
        doc_id, "small.txt", ExtractedText(text=text), on_progress=lambda done, total: reported.append((done, total))
    )

    assert 1 < count <= 20  # small enough that every chunk should report individually
    assert reported == [(i, count) for i in range(0, count + 1)]


def test_reset_drops_everything(index):
    doc_id = uuid.uuid4()
    index.index_document(doc_id, "a.txt", ExtractedText(text="alpha beta gamma"))
    index.reset()
    assert index.search("alpha", limit=3) == []


def _pages_of(hits, document_id) -> list[int | None]:
    return [hit.page for hit in hits if hit.document_id == document_id]


def test_a_hit_reports_the_page_its_chunk_starts_on(index):
    """Chunking runs over the whole text; the page comes from where the chunk starts in it."""
    doc_id = uuid.uuid4()
    first_page = "The breaker panel is behind the garage door. " * 40
    second_page = "The condenser fan is on the roof. " * 40
    text = f"{first_page}\n{second_page}"

    index.index_document(
        doc_id, "panel.txt", ExtractedText(text=text, page_starts=(0, len(first_page) + 1))
    )

    # Documents from earlier tests share the table, so each search is narrowed to this one.
    assert _pages_of(index.search("breaker panel", limit=5), doc_id)[0] == 1
    assert _pages_of(index.search("condenser fan on the roof", limit=5), doc_id)[0] == 2


def test_a_hit_from_a_document_without_pages_reports_none(index):
    doc_id = uuid.uuid4()

    index.index_document(doc_id, "notes.md", ExtractedText(text="alpha beta gamma"))

    assert _pages_of(index.search("alpha beta gamma", limit=5), doc_id) == [None]
