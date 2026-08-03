"""Engine construction for FSM processes: the pool sizing this deployment runs with.

The generic builder lives in fsm.core.db, and the declarative Base in fsm.shared.db so context
adapters can register tables without importing platform.
"""

from sqlalchemy import Engine

from fsm.core.db import build_engine
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
    """Build the engine an FSM process runs on, at this deployment's pool sizing."""
    return build_engine(
        settings.database_url.get_secret_value(),
        pool_size=POOL_SIZE,
        max_overflow=MAX_OVERFLOW,
    )
