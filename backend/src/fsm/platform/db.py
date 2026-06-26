"""Database engine and session factory for SQLAlchemy."""

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from fsm.platform.config import Settings


class Base(DeclarativeBase):
    """Declarative base; bounded contexts register their ORM tables against it."""


def create_engine_from_settings(settings: Settings) -> Engine:
    """Build a SQLAlchemy engine from configuration."""
    return create_engine(settings.database_url.get_secret_value(), pool_pre_ping=True)


def session_factory(engine: Engine) -> sessionmaker[Session]:
    """Build a session factory bound to the given engine."""
    return sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
