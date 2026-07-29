"""SQLAlchemy ORM row classes for the assist bounded context."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Integer, LargeBinary, Text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from fsm.shared.db import Base


class KbDocumentRow(Base):
    """Source of truth for one knowledge-base document.

    Holds the raw uploaded bytes so the derived vector index can always be rebuilt.
    chunk_count and embedding_model mirror the current index state for this document.
    uploaded_by is a plain user id, not a foreign key — cross-context references stay by-id.
    """

    __tablename__ = "kb_document"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    media_type: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding_model: Mapped[str] = mapped_column(Text, nullable=False)
