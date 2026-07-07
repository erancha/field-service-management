"""SQLAlchemy ORM row classes for the notifications bounded context."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from fsm.shared.db import Base


class NotificationEventRow(Base):
    """Shared content of one appointment lifecycle event.

    Holds the subject and body that every recipient of the event reads; written once per event.
    """

    __tablename__ = "notification_event"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)


class NotificationRecipientRow(Base):
    """One recipient's delivery of a notification event.

    user_id is indexed because feed queries always filter by user. read is per recipient, so
    each party's unread state is independent.
    """

    __tablename__ = "notification_recipient"
    __table_args__ = (
        UniqueConstraint("notification_event_id", "user_id", name="uq_notification_recipient"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, nullable=False)
    notification_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("notification_event.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    read: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
