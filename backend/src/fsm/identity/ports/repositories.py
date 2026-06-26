"""Repository port definitions for the identity bounded context.

These protocols define the persistence boundary for User entities. Concrete
adapters (SQL, in-memory) implement these without the domain layer depending
on them.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from fsm.identity.domain.errors import NotFoundError
from fsm.identity.domain.user import User

__all__ = ["NotFoundError", "UserRepository"]


@runtime_checkable
class UserRepository(Protocol):
    """Persistence contract for User entities."""

    def get_by_google_sub(self, google_sub: str) -> User | None:
        """Return the user with the given Google subject identifier, or None when absent.

        Returning None (rather than raising) lets the sign-in use-case decide
        whether to create a new account or treat absence as an error.
        """
        ...

    def add(self, user: User) -> None:
        """Persist a new user; caller ensures the id is unique.

        Raises DuplicateGoogleSub when the google_sub already exists in the store.
        """
        ...

    def save(self, user: User) -> None:
        """Persist mutations to an already-stored user."""
        ...

    def get(self, user_id: UUID) -> User:
        """Return the user with the given id.

        Raises NotFoundError if no such user exists.
        """
        ...
