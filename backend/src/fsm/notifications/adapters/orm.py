"""SQLAlchemy ORM row class for the notifications bounded context."""
from __future__ import annotations

from sqlalchemy import Boolean, String, Text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from fsm.shared.db import Base


class NotificationRow(Base):
    """Persistent row for one in-app notification.

    user_id is indexed because feed queries always filter by user. read starts
    False; mark_read sets it to True in-place.
    """

    __tablename__ = "notification"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, nullable=False)
    user_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[TIMESTAMP] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    read: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
