"""SQLAlchemy implementation of the KbDocumentRepository port."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from fsm.assist.adapters.orm import KbDocumentRow
from fsm.assist.domain.document import KbDocument
from fsm.assist.domain.errors import DocumentNotFound


def _to_document(row: KbDocumentRow) -> KbDocument:
    return KbDocument(
        id=row.id,
        filename=row.filename,
        media_type=row.media_type,
        size_bytes=row.size_bytes,
        uploaded_by=row.uploaded_by,
        uploaded_at=row.uploaded_at,
        chunk_count=row.chunk_count,
        embedding_model=row.embedding_model,
    )


class SqlAlchemyKbDocumentRepository:
    """Session-scoped repository for the kb_document table. Caller owns the transaction."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def _row(self, document_id: uuid.UUID) -> KbDocumentRow:
        row = self._session.get(KbDocumentRow, document_id)
        if row is None:
            raise DocumentNotFound(f"No knowledge-base document with id {document_id}")
        return row

    def add(self, document: KbDocument, content: bytes) -> None:
        self._session.add(
            KbDocumentRow(
                id=document.id,
                filename=document.filename,
                media_type=document.media_type,
                content=content,
                size_bytes=document.size_bytes,
                uploaded_by=document.uploaded_by,
                uploaded_at=document.uploaded_at,
                chunk_count=document.chunk_count,
                embedding_model=document.embedding_model,
            )
        )
        self._session.flush()

    def get(self, document_id: uuid.UUID) -> KbDocument:
        return _to_document(self._row(document_id))

    def get_content(self, document_id: uuid.UUID) -> bytes:
        return self._row(document_id).content

    def list_all(self) -> list[KbDocument]:
        rows = self._session.scalars(
            select(KbDocumentRow).order_by(KbDocumentRow.uploaded_at.desc())
        )
        return [_to_document(row) for row in rows]

    def remove(self, document_id: uuid.UUID) -> None:
        self._session.delete(self._row(document_id))
        self._session.flush()

    def update_index_state(
        self, document_id: uuid.UUID, chunk_count: int, embedding_model: str
    ) -> None:
        row = self._row(document_id)
        row.chunk_count = chunk_count
        row.embedding_model = embedding_model
        self._session.flush()
