"""Guarded identity lookups for platform composition roots.

Lookups are best-effort: every referenced user is created at OAuth sign-in and never deleted, so a
failed lookup indicates corrupt data or a broken session — it is logged as an error, and the caller
degrades to generic content rather than failing the surrounding transaction.
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy.orm import Session

from fsm.identity.adapters.repositories import SqlAlchemyUserRepository
from fsm.identity.domain.user import User

_log = logging.getLogger(__name__)


def load_user(session: Session, user_id: uuid.UUID) -> User | None:
    """Return the user for user_id, or None (logged as an error) when the lookup fails."""
    try:
        return SqlAlchemyUserRepository(session).get(user_id)
    except Exception:
        _log.exception("User lookup failed for user_id=%s", user_id)
        return None
