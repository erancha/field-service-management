"""Declarative ORM base shared by every bounded context's adapters.

A single Base keeps all tables in one SQLAlchemy metadata so Alembic autogenerate and
create_all see the whole schema. Engine and session construction stay in platform — this
module carries no connection state.
"""
from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base; bounded contexts register their ORM tables against it."""
