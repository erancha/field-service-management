"""Round-trips the kb_document table through the SQLAlchemy repository."""
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from fsm.assist.adapters.document_repository import SqlAlchemyKbDocumentRepository
from fsm.assist.domain.document import KbDocument
from fsm.assist.domain.errors import DocumentNotFound


def _doc(**overrides) -> KbDocument:
    base = dict(
        id=uuid.uuid4(),
        filename="guide.md",
        media_type="text/markdown",
        size_bytes=5,
        uploaded_by=uuid.uuid4(),
        uploaded_at=datetime(2026, 7, 28, tzinfo=UTC),
        chunk_count=0,
        embedding_model="openai:text-embedding-3-small",
    )
    return KbDocument(**{**base, **overrides})


def test_add_get_list_remove(pg_engine):
    with Session(pg_engine) as session:
        repo = SqlAlchemyKbDocumentRepository(session)
        doc = _doc()
        repo.add(doc, b"hello")
        session.commit()

        assert repo.get(doc.id) == doc
        assert repo.get_content(doc.id) == b"hello"
        assert [d.id for d in repo.list_all()] == [doc.id]

        repo.update_index_state(doc.id, 3, "openai:new-model")
        session.commit()
        updated = repo.get(doc.id)
        assert (updated.chunk_count, updated.embedding_model) == (3, "openai:new-model")

        repo.remove(doc.id)
        session.commit()
        assert repo.list_all() == []


def test_find_by_content_matches_byte_identical_uploads(pg_engine):
    with Session(pg_engine) as session:
        repo = SqlAlchemyKbDocumentRepository(session)
        doc = _doc()
        repo.add(doc, b"hello")

        assert repo.find_by_content(b"hello") == doc
        assert repo.find_by_content(b"other bytes") is None


def test_storing_byte_identical_content_twice_is_rejected_by_the_database(pg_engine):
    """The unique hash index is the race backstop when two uploads slip past the service check."""
    with Session(pg_engine) as session:
        repo = SqlAlchemyKbDocumentRepository(session)
        repo.add(_doc(), b"same bytes")
        with pytest.raises(IntegrityError):
            repo.add(_doc(), b"same bytes")


def test_get_unknown_raises(pg_engine):
    with Session(pg_engine) as session:
        repo = SqlAlchemyKbDocumentRepository(session)
        with pytest.raises(DocumentNotFound):
            repo.get(uuid.uuid4())
