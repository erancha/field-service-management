"""In-memory fakes for the assist ports, shared across assist test modules."""
from __future__ import annotations

import uuid

from fsm.assist.domain.document import KbDocument
from fsm.assist.domain.errors import DocumentNotFound
from fsm.assist.ports.document_index import SearchHit


class FakeKbDocumentRepository:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, KbDocument] = {}
        self.contents: dict[uuid.UUID, bytes] = {}

    def add(self, document: KbDocument, content: bytes) -> None:
        self.rows[document.id] = document
        self.contents[document.id] = content

    def get(self, document_id: uuid.UUID) -> KbDocument:
        try:
            return self.rows[document_id]
        except KeyError:
            raise DocumentNotFound(str(document_id)) from None

    def get_content(self, document_id: uuid.UUID) -> bytes:
        try:
            return self.contents[document_id]
        except KeyError:
            raise DocumentNotFound(str(document_id)) from None

    def list_all(self) -> list[KbDocument]:
        return sorted(self.rows.values(), key=lambda d: d.uploaded_at, reverse=True)

    def remove(self, document_id: uuid.UUID) -> None:
        self.get(document_id)
        del self.rows[document_id]
        del self.contents[document_id]

    def update_index_state(
        self, document_id: uuid.UUID, chunk_count: int, embedding_model: str
    ) -> None:
        import dataclasses

        self.rows[document_id] = dataclasses.replace(
            self.get(document_id), chunk_count=chunk_count, embedding_model=embedding_model
        )


class FakeDocumentIndex:
    """Keeps whole texts per document; search returns chunks whose text contains the query."""

    def __init__(self) -> None:
        self.texts: dict[uuid.UUID, tuple[str, str]] = {}  # id -> (filename, text)
        self.reset_calls = 0

    def index_document(self, document_id: uuid.UUID, filename: str, text: str) -> int:
        self.texts[document_id] = (filename, text)
        return 1

    def remove_document(self, document_id: uuid.UUID, chunk_count: int) -> None:
        self.texts.pop(document_id, None)

    def search(self, query: str, limit: int) -> list[SearchHit]:
        hits = [
            SearchHit(document_id=doc_id, filename=filename, content=text, score=1.0)
            for doc_id, (filename, text) in self.texts.items()
            if query.lower() in text.lower()
        ]
        return hits[:limit]

    def reset(self) -> None:
        self.texts.clear()
        self.reset_calls += 1


class FakeTextExtractor:
    """Decodes bytes as UTF-8, whatever the claimed type."""

    def extract(self, filename: str, media_type: str, content: bytes) -> str:
        return content.decode("utf-8")
