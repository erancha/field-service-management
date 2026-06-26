"""SQLAlchemy Unit-of-Work adapter for the scheduling bounded context.

SqlAlchemyUnitOfWork owns the session lifecycle. One session is opened on
__enter__, shared by all three repositories for the duration of the with-block,
and committed only when commit() is called explicitly. __exit__ rolls back any
uncommitted work and always closes the session.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from fsm.scheduling.adapters.outbox_repository import SqlAlchemyOutboxRepository
from fsm.scheduling.adapters.repositories import (
    SqlAlchemyAppointmentRepository,
    SqlAlchemyServiceCallRepository,
)

_log = logging.getLogger(__name__)


class SqlAlchemyUnitOfWork:
    """Context-manager that binds all three scheduling repositories to one transaction."""

    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None
        self._committed = False

    def __enter__(self) -> "SqlAlchemyUnitOfWork":
        self._session = self._session_factory()
        self._committed = False
        self.service_calls = SqlAlchemyServiceCallRepository(self._session)
        self.appointments = SqlAlchemyAppointmentRepository(self._session)
        self.outbox = SqlAlchemyOutboxRepository(self._session)
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        assert self._session is not None
        try:
            if not self._committed:
                _log.debug("UnitOfWork rolling back uncommitted transaction")
                self._session.rollback()
        finally:
            self._session.close()
            self._session = None

    @property
    def session(self) -> Session:
        """Return the active session. Only valid inside a with-block."""
        assert self._session is not None, "session accessed outside a with-block"
        return self._session

    def commit(self) -> None:
        """Commit all pending mutations in the current transaction."""
        assert self._session is not None, "commit() called outside a with-block"
        _log.debug("UnitOfWork committing transaction")
        self._session.commit()
        self._committed = True
