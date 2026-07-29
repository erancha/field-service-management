"""Outbound port for the similarity-search index over document chunks."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class SearchHit:
    """One matching chunk, with enough context to cite its source document.

    score is cosine similarity to the query: 1 is an exact match, lower is farther.
    """

    document_id: uuid.UUID
    filename: str
    content: str
    score: float


@runtime_checkable
class DocumentIndex(Protocol):
    """Chunk, embed, store, and search document text. Chunking strategy is the adapter's."""

    def index_document(self, document_id: uuid.UUID, filename: str, text: str) -> int:
        """Split text into chunks and index them; returns the number of chunks written."""
        ...

    def remove_document(self, document_id: uuid.UUID, chunk_count: int) -> None:
        """Remove the document's chunks. chunk_count is the count recorded at indexing time."""
        ...

    def search(self, query: str, limit: int) -> list[SearchHit]:
        """Most similar chunks across all documents."""
        ...

    def reset(self) -> None:
        """Drop the whole index; used before a full re-index."""
        ...
