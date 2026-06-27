"""Database engine and session factory for SQLAlchemy."""

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from fsm.platform.config import Settings


class Base(DeclarativeBase):
    """Declarative base; bounded contexts register their ORM tables against it."""


def create_engine_from_settings(settings: Settings) -> Engine:
    """Build a SQLAlchemy engine; pool_pre_ping validates a pooled connection before
    use so a stale or server-dropped connection is replaced rather than erroring a query."""
    return create_engine(settings.database_url.get_secret_value(), pool_pre_ping=True)


def session_factory(engine: Engine) -> sessionmaker[Session]:
    """Build a session factory; expire_on_commit is off so ORM objects stay readable
    after commit, letting callers return persisted entities outside the transaction."""
    return sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
