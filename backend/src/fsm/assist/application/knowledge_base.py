"""Application service for the knowledge base: ingestion, management, search, re-index."""
from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from functools import partial
from pathlib import PurePosixPath
from typing import Literal

from fsm.assist.domain.document import KbDocument
from fsm.assist.domain.errors import (
    DuplicateDocument,
    EmptyDocumentText,
    IndexModelMismatch,
    UnsupportedDocumentType,
)
from fsm.assist.ports.document_index import DocumentIndex, SearchHit
from fsm.assist.ports.document_repository import KbDocumentRepository
from fsm.assist.ports.text_extractor import TextExtractor

SUPPORTED_EXTENSIONS = {".pdf", ".md", ".txt"}

IngestPhase = Literal["extracting", "indexing"]

# Called with (phase, units done, total units): pages while extracting, chunks while indexing.
IngestProgressCallback = Callable[[IngestPhase, int, int], None]


@dataclass(frozen=True)
class IngestResult:
    """Outcome of one upload run: the stored document plus where the ingest time went."""

    document: KbDocument
    extract_seconds: float
    index_seconds: float


def _utc_now() -> datetime:
    return datetime.now(UTC)


class KnowledgeBaseService:
    """Coordinates the document store, text extraction, and the vector index.

    The repository is the source of truth; the index is derived data written over its own
    connection, outside the caller's transaction. Writes go document-row first, index second,
    so an indexing failure raises and rolls the row back. Chunks already written stay behind
    whenever the row is rolled back — after a commit failure, or after a partial indexing run,
    since the index writes in batches — and a re-index rebuilds the chunk table from the stored
    rows to clear them.
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
        self,
        filename: str,
        media_type: str,
        content: bytes,
        uploaded_by: uuid.UUID,
        on_progress: IngestProgressCallback | None = None,
    ) -> IngestResult:
        """Store the document and index its text, reporting phase-tagged progress if asked.

        on_progress is called with ("extracting", pages done, total pages) as text is pulled from
        the file, then ("indexing", chunks written, total chunks) as embedded batches land. Each
        port reports plain (done, total); this layer is what tags the phase. The result carries
        each phase's duration, read from the service clock around the port calls.
        """
        extension = PurePosixPath(filename).suffix.lower()
        if extension not in SUPPORTED_EXTENSIONS:
            raise UnsupportedDocumentType(
                f'"{filename}" is not a supported document type (pdf, md, txt)'
            )
        # Byte-identical content is refused before extraction so a re-upload never pays the
        # extract-and-embed cost again; the unique content hash in the store backstops races.
        existing = self._documents.find_by_content(content)
        if existing is not None:
            raise DuplicateDocument(
                f'"{filename}" is already in the knowledge base as "{existing.filename}"'
                f" (uploaded {existing.uploaded_at:%Y-%m-%d %H:%M} UTC)"
            )
        extract_progress = None if on_progress is None else partial(on_progress, "extracting")
        extract_started = self._clock()
        extracted = self._extractor.extract(filename, media_type, content, extract_progress)
        extract_seconds = (self._clock() - extract_started).total_seconds()
        if not extracted.text.strip():
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
        index_progress = None if on_progress is None else partial(on_progress, "indexing")
        index_started = self._clock()
        chunk_count = self._index.index_document(
            document.id, filename, extracted, index_progress
        )
        index_seconds = (self._clock() - index_started).total_seconds()
        self._documents.update_index_state(document.id, chunk_count, self._embedding_model)
        return IngestResult(
            document=replace(document, chunk_count=chunk_count),
            extract_seconds=extract_seconds,
            index_seconds=index_seconds,
        )

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
            extracted = self._extractor.extract(
                document.filename, document.media_type, content
            )
            chunk_count = self._index.index_document(
                document.id, document.filename, extracted
            )
            self._documents.update_index_state(
                document.id, chunk_count, self._embedding_model
            )
        return len(documents)
