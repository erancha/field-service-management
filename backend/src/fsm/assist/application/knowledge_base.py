"""Application service for the knowledge base: ingestion, management, search, re-index."""
from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import PurePosixPath

from fsm.assist.domain.document import KbDocument
from fsm.assist.domain.errors import (
    EmptyDocumentText,
    IndexModelMismatch,
    UnsupportedDocumentType,
)
from fsm.assist.ports.document_index import DocumentIndex, SearchHit
from fsm.assist.ports.document_repository import KbDocumentRepository
from fsm.assist.ports.text_extractor import TextExtractor

SUPPORTED_EXTENSIONS = {".pdf", ".md", ".txt"}


def _utc_now() -> datetime:
    return datetime.now(UTC)


class KnowledgeBaseService:
    """Coordinates the document store, text extraction, and the vector index.

    The repository is the source of truth; the index is derived data written over its own
    connection, outside the caller's transaction. Writes go document-row first, index second,
    so an indexing failure raises and rolls the row back. The reverse gap remains: a commit
    failure after indexing leaves orphaned chunks, and a re-index rebuilds the chunk table
    from the stored rows to clear them.
    """

    def __init__(
        self,
        documents: KbDocumentRepository,
        index: DocumentIndex,
        extractor: TextExtractor,
        embedding_model: str,
        *,
        clock: Callable[[], datetime] = _utc_now,
        id_factory: Callable[[], uuid.UUID] = uuid.uuid4,
    ) -> None:
        self._documents = documents
        self._index = index
        self._extractor = extractor
        self._embedding_model = embedding_model
        self._clock = clock
        self._id_factory = id_factory

    def upload(
        self, filename: str, media_type: str, content: bytes, uploaded_by: uuid.UUID
    ) -> KbDocument:
        extension = PurePosixPath(filename).suffix.lower()
        if extension not in SUPPORTED_EXTENSIONS:
            raise UnsupportedDocumentType(
                f'"{filename}" is not a supported document type (pdf, md, txt)'
            )
        text = self._extractor.extract(filename, media_type, content)
        if not text.strip():
            raise EmptyDocumentText(
                f'No text could be extracted from "{filename}" — scanned or image-only'
                " documents cannot be indexed"
            )
        document = KbDocument(
            id=self._id_factory(),
            filename=filename,
            media_type=media_type,
            size_bytes=len(content),
            uploaded_by=uploaded_by,
            uploaded_at=self._clock(),
            chunk_count=0,
            embedding_model=self._embedding_model,
        )
        self._documents.add(document, content)
        chunk_count = self._index.index_document(document.id, filename, text)
        self._documents.update_index_state(document.id, chunk_count, self._embedding_model)
        return replace(document, chunk_count=chunk_count)

    def list_documents(self) -> list[KbDocument]:
        return self._documents.list_all()

    def delete(self, document_id: uuid.UUID) -> None:
        document = self._documents.get(document_id)
        self._index.remove_document(document.id, document.chunk_count)
        self._documents.remove(document.id)

    def needs_reindex(self) -> bool:
        return any(
            d.embedding_model != self._embedding_model for d in self._documents.list_all()
        )

    def search(self, query: str, limit: int = 5) -> list[SearchHit]:
        if self.needs_reindex():
            raise IndexModelMismatch(
                "The index was built with a different embedding model than"
                f" {self._embedding_model}; re-index the documents to search again"
            )
        return self._index.search(query, limit)

    def reindex(self) -> int:
        self._index.reset()
        documents = self._documents.list_all()
        for document in documents:
            content = self._documents.get_content(document.id)
            text = self._extractor.extract(document.filename, document.media_type, content)
            chunk_count = self._index.index_document(document.id, document.filename, text)
            self._documents.update_index_state(
                document.id, chunk_count, self._embedding_model
            )
        return len(documents)
