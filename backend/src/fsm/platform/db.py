"""Database engine and session factory for SQLAlchemy.

The declarative Base lives in fsm.shared.db so context adapters can register tables
without importing platform.
"""

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from fsm.platform.config import Settings

POOL_SIZE = 20
"""Connections held open per process, sized above the expected concurrent triage chats.

A streaming triage turn holds its connection for the whole model response — seconds to tens of
seconds — rather than the milliseconds every other request needs. The pool must therefore exceed
the number of chats expected at once, or streaming turns occupy every connection and unrelated
requests (booking, appointments, /ready) block until the pool timeout.
"""

MAX_OVERFLOW = 5
"""Burst connections beyond POOL_SIZE, so short requests are still served while chats hold theirs.

POOL_SIZE + MAX_OVERFLOW is the per-process ceiling, and the arithmetic that bounds it is the
database server's, not this process's. PostgreSQL's default max_connections of 100 reserves 3 for
superusers, leaving 97: the three role processes claim 75 of those, and the rest has to cover the
alembic migration service, the one-off runners that each build their own engine, and an operator's
psql. Adding role replicas multiplies the ceiling, so max_connections must rise with them.
"""


def create_engine_from_settings(settings: Settings) -> Engine:
    """Build a SQLAlchemy engine; pool_pre_ping validates a pooled connection before
    use so a stale or server-dropped connection is replaced rather than erroring a query."""
    return create_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        pool_size=POOL_SIZE,
        max_overflow=MAX_OVERFLOW,
    )


def session_factory(engine: Engine) -> sessionmaker[Session]:
    """Build a session factory; expire_on_commit is off so ORM objects stay readable
    after commit, letting callers return persisted entities outside the transaction."""
    return sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
