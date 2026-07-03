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
from fsm.scheduling.domain.contact_info import ContactInfo

_log = logging.getLogger(__name__)


def load_user(session: Session, user_id: uuid.UUID) -> User | None:
    """Return the user for user_id, or None (logged as an error) when the lookup fails."""
    try:
        return SqlAlchemyUserRepository(session).get(user_id)
    except Exception:
        _log.exception("User lookup failed for user_id=%s", user_id)
        return None


def build_contact_resolver(session: Session):
    """Return a callable mapping a user id to their ContactInfo (address, phone) on `session`.

    Feeds AppointmentService.book_appointment so the scheduling layer enforces contact presence
    without importing identity. A missing user yields empty ContactInfo, so booking fails closed.
    """
    def _resolve(user_id: uuid.UUID) -> ContactInfo:
        user = load_user(session, user_id)
        if user is None:
            return ContactInfo()
        return ContactInfo(address=user.address, phone=user.phone)

    return _resolve
