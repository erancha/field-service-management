"""SQLAlchemy ORM row class for the identity bounded context."""
from __future__ import annotations

from sqlalchemy import Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from fsm.platform.db import Base


class UserRow(Base):
    """Persistent row for an application user.

    Table is named app_user to avoid colliding with the PostgreSQL reserved keyword 'user'.
    """

    __tablename__ = "app_user"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    google_sub: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    email: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        Index("ix_app_user_google_sub", "google_sub"),
    )
