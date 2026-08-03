"""Cross-process lease: a named hold at most one process has at a time.

Callers that must run exactly one copy of some work take the lease first and run only while they
hold it. The port carries no database in its signature, so a deployment on another store supplies
its own adapter and the policy built on top — attempt, run, retry — stays unchanged.
"""
from __future__ import annotations

from typing import Protocol

from sqlalchemy import text


class Lease(Protocol):
    """An exclusive hold: at most one holder at a time, given up by releasing or by dying."""

    def acquire(self) -> bool:
        """Take the hold, or report that another process has it."""
        ...

    def release(self) -> None:
        """Give up the hold so another process can take it."""
        ...


class PostgresAdvisoryLease:
    """Lease held by a session-level Postgres advisory lock on a session of its own.

    The lock lives exactly as long as that session's connection, so a process that dies without
    releasing loses the lease as soon as the database notices the dropped connection — which is
    what lets a standby take over unprompted. The session is held open for the duration of the
    hold and belongs to no unit of work, which is why the lease opens its own rather than
    borrowing a caller's.
    """

    def __init__(self, session_factory, key: int) -> None:
        self._session_factory = session_factory
        self._key = key
        self._session = None

    def acquire(self) -> bool:
        held = self._session_factory()
        acquired = held.execute(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": self._key}
        ).scalar()
        held.commit()
        if not acquired:
            held.close()
            return False
        self._session = held
        return True

    def release(self) -> None:
        held = self._session
        if held is None:
            raise RuntimeError("Lease released without being held")
        try:
            held.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": self._key})
            held.commit()
        finally:
            held.close()
            self._session = None
