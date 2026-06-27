"""In-memory fake implementations of the identity port protocols.

These fakes are test-support only and are never shipped as part of the production
package. They satisfy each protocol structurally and can be verified with
isinstance checks because every protocol is @runtime_checkable.
"""
from __future__ import annotations

from uuid import UUID

from fsm.identity.domain.errors import AuthenticationError, NotFoundError
from fsm.identity.domain.role import Role
from fsm.identity.domain.role_status import RoleStatus
from fsm.identity.domain.user import User
from fsm.identity.ports.auth import VerifiedIdentity


class InMemoryUserRepository:
    """Dict-backed UserRepository. Stores references; mutations visible immediately."""

    def __init__(self) -> None:
        self._store: dict[UUID, User] = {}
        self._save_count: int = 0

    def get_by_google_sub(self, google_sub: str) -> User | None:
        for user in self._store.values():
            if user.google_sub == google_sub:
                return user
        return None

    def add(self, user: User) -> None:
        self._store[user.id] = user

    def get(self, user_id: UUID) -> User:
        try:
            return self._store[user_id]
        except KeyError:
            raise NotFoundError(f"User {user_id!r} not found")

    def get_all(self) -> list[User]:
        """Return all stored users (test helper)."""
        return list(self._store.values())

    @property
    def save_count(self) -> int:
        """Number of times save() has been called (test helper)."""
        return self._save_count

    def save(self, user: User) -> None:
        self._save_count += 1
        self._store[user.id] = user

    def list_pending_technicians(self) -> list[User]:
        return [
            user
            for user in self._store.values()
            if user.role is Role.TECHNICIAN and user.role_status is RoleStatus.PENDING
        ]


class FakeAuthPort:
    """Configurable AuthPort for tests.

    Register credential→identity mappings with register(); verify() returns the
    mapped identity or raises AuthenticationError for unregistered credentials.
    """

    def __init__(self) -> None:
        self._credentials: dict[str, VerifiedIdentity] = {}

    def register(self, credential: str, identity: VerifiedIdentity) -> None:
        """Map a credential string to a VerifiedIdentity (test helper)."""
        self._credentials[credential] = identity

    def verify(self, credential: str) -> VerifiedIdentity:
        try:
            return self._credentials[credential]
        except KeyError:
            raise AuthenticationError(f"Credential {credential!r} is invalid or unregistered")
