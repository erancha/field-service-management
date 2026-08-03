"""SQLAlchemy ORM row classes for the assist bounded context."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, LargeBinary, Text, text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from fsm.shared.db import Base


class KbDocumentRow(Base):
    """Source of truth for one knowledge-base document.

    Holds the raw uploaded bytes so the derived vector index can always be rebuilt.
    chunk_count and embedding_model mirror the current index state for this document.
    uploaded_by is a plain user id, not a foreign key — cross-context references stay by-id.

    content_sha256 is a SHA-256 hash of the raw bytes; its unique index makes byte-identical
    re-uploads fail in the database even when two uploads race past the service-level check.
    """

    __tablename__ = "kb_document"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    media_type: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    content_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding_model: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        Index("uq_kb_document_content_sha256", "content_sha256", unique=True),
    )


class AssistConversationRow(Base):
    """One triage exchange. service_call_id is set on escalation only.

    customer_id and service_call_id are plain user and service-call ids, not foreign keys —
    cross-context references stay by-id.

    equipment is overwritten by each identification, so the column holds the current one and no
    history of the corrections behind it.

    A customer has at most one ACTIVE conversation at a time; the partial unique index enforces
    that in the database, so concurrent start requests cannot each open one.
    """

    __tablename__ = "assist_conversation"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    service_call_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    equipment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_assist_conversation_customer_status", "customer_id", "status"),
        Index(
            "uq_assist_conversation_one_active_per_customer",
            "customer_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
        ),
    )


class AssistMessageRow(Base):
    """One turn of a conversation. seq orders the turns within a conversation.

    seq is unique per conversation, so two turns racing to claim the same position fail loudly
    rather than leaving the replay order to chance.
    """

    __tablename__ = "assist_message"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, nullable=False)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assist_conversation.id", ondelete="CASCADE"),
        nullable=False,
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_assist_message_conversation_seq", "conversation_id", "seq", unique=True),
    )


class AssistPhotoRow(Base):
    """Metadata for one customer photo; the bytes live in object storage under object_key.

    message_id is NULL until the customer sends the turn that carries the photo; binding it is
    what makes the photo part of the transcript and, on escalation, of the service call.
    """

    __tablename__ = "assist_photo"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, nullable=False)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assist_conversation.id", ondelete="CASCADE"),
        nullable=False,
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assist_message.id", ondelete="CASCADE"), nullable=True
    )
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    media_type: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_assist_photo_conversation", "conversation_id"),
        Index("ix_assist_photo_message", "message_id"),
    )
