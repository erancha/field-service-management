"""SQLAlchemy ORM row class for the calendar bounded context.

technician_id is used as the primary key: each technician may have at most one
calendar connection. The unique index enforces this at the database level.
"""
from __future__ import annotations

import uuid

from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from fsm.shared.db import Base


class CalendarConnectionRow(Base):
    """Persistent row for a technician's calendar connection.

    technician_id is both the primary key and the uniqueness anchor — the
    UNIQUE constraint is enforced by the primary key itself, and the index
    makes point lookups efficient.
    """

    __tablename__ = "calendar_connection"

    technician_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    fsm_calendar_id: Mapped[str] = mapped_column(String, nullable=False)
    encrypted_refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    sync_token: Mapped[str | None] = mapped_column(Text, nullable=True)
