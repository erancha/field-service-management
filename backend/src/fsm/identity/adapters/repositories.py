"""SQLAlchemy repository adapter for the identity bounded context."""
from __future__ import annotations

import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from fsm.identity.adapters.orm import UserRow
from fsm.identity.domain.errors import DuplicateGoogleSub, NotFoundError
from fsm.identity.domain.role import Role
from fsm.identity.domain.user import User

_GOOGLE_SUB_CONSTRAINT = "uq_app_user_google_sub"


def _translate_integrity_error(exc: IntegrityError) -> None:
    """Raise DuplicateGoogleSub for the google_sub uniqueness constraint; let all other
    IntegrityErrors propagate unchanged.

    Inspects the psycopg diagnostic constraint_name first; falls back to a substring
    check on the stringified original error for other drivers.
    """
    constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
    if constraint is None:
        constraint = _GOOGLE_SUB_CONSTRAINT if _GOOGLE_SUB_CONSTRAINT in str(exc.orig) else None
    if constraint == _GOOGLE_SUB_CONSTRAINT:
        raise DuplicateGoogleSub(
            f"A user with the same Google subject identifier already exists (constraint: {_GOOGLE_SUB_CONSTRAINT})"
        ) from exc
    raise exc


def _row_to_user(row: UserRow) -> User:
    return User(
        id=row.id,
        google_sub=row.google_sub,
        email=row.email,
        name=row.name,
        role=Role(row.role),
    )


def _user_to_row(user: User) -> UserRow:
    return UserRow(
        id=user.id,
        google_sub=user.google_sub,
        email=user.email,
        name=user.name,
        role=user.role.value,
    )


class SqlAlchemyUserRepository:
    """Session-scoped SQLAlchemy adapter for User persistence."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_google_sub(self, google_sub: str) -> User | None:
        """Return the user with the given Google subject identifier, or None when absent."""
        row = (
            self._session.query(UserRow)
            .filter(UserRow.google_sub == google_sub)
            .one_or_none()
        )
        return _row_to_user(row) if row is not None else None

    def add(self, user: User) -> None:
        """Insert a new user row.

        Raises DuplicateGoogleSub when the google_sub already exists in the database;
        callers need only ensure the id is unique.
        """
        try:
            self._session.add(_user_to_row(user))
            self._session.flush()
        except IntegrityError as exc:
            _translate_integrity_error(exc)

    def save(self, user: User) -> None:
        """Persist mutations to an already-stored user; caller owns the transaction."""
        row = self._session.get(UserRow, user.id)
        if row is None:
            raise NotFoundError(f"User {user.id!r} not found")
        row.google_sub = user.google_sub
        row.email = user.email
        row.name = user.name
        row.role = user.role.value
        self._session.flush()

    def get(self, user_id: uuid.UUID) -> User:
        """Return the user with the given id.

        Raises NotFoundError if absent.
        """
        row = self._session.get(UserRow, user_id)
        if row is None:
            raise NotFoundError(f"User {user_id!r} not found")
        return _row_to_user(row)
