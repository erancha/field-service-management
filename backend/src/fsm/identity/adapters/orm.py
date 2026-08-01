"""SQLAlchemy ORM row class for the identity bounded context."""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Index, String
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from fsm.shared.db import Base


class UserRow(Base):
    """Persistent row for an application user.

    Table is named app_user to avoid colliding with the PostgreSQL reserved keyword 'user'.

    role is the access the user claims; role_status (PENDING/APPROVED/REJECTED) is whether that
    access is granted. role_decided_at / role_decided_by record the administrator decision that
    last set role_status and are null until a decision is made.
    """

    __tablename__ = "app_user"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    google_sub: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    email: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    role_status: Mapped[str] = mapped_column(String, nullable=False)
    role_decided_at: Mapped[dt.datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    role_decided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    address: Mapped[str | None] = mapped_column(String, nullable=True)
    phone: Mapped[str | None] = mapped_column(String, nullable=True)
    assist_disclaimer_accepted_at: Mapped[dt.datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_app_user_google_sub", "google_sub"),
    )
