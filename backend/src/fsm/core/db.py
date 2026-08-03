"""SQLAlchemy engine and session-factory construction."""

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def build_engine(database_url: str, *, pool_size: int, max_overflow: int) -> Engine:
    """Build a SQLAlchemy engine; pool_pre_ping validates a pooled connection before
    use so a stale or server-dropped connection is replaced rather than erroring a query.

    Pool sizing is deployment arithmetic — how long this application's requests hold a
    connection, and how many connections the database server has to share out — so the
    caller supplies both numbers.
    """
    return create_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=pool_size,
        max_overflow=max_overflow,
    )


def session_factory(engine: Engine) -> sessionmaker[Session]:
    """Build a session factory; expire_on_commit is off so ORM objects stay readable
    after commit, letting callers return persisted entities outside the transaction."""
    return sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
