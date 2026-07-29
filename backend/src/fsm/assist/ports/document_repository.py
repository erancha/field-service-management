"""Outbound port for persisting knowledge-base documents."""
from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable

from fsm.assist.domain.document import KbDocument


@runtime_checkable
class KbDocumentRepository(Protocol):
    """Stores document metadata and raw content; the index is derived data, kept elsewhere."""

    def add(self, document: KbDocument, content: bytes) -> None:
        """Persist the document row with its raw content."""
        ...

    def get(self, document_id: uuid.UUID) -> KbDocument:
        """Return the document; raises DocumentNotFound."""
        ...

    def get_content(self, document_id: uuid.UUID) -> bytes:
        """Return the raw uploaded bytes; raises DocumentNotFound."""
        ...

    def list_all(self) -> list[KbDocument]:
        """All documents, newest first."""
        ...

    def remove(self, document_id: uuid.UUID) -> None:
        """Delete the document row; raises DocumentNotFound."""
        ...

    def update_index_state(
        self, document_id: uuid.UUID, chunk_count: int, embedding_model: str
    ) -> None:
        """Record how the document is currently represented in the index."""
        ...
