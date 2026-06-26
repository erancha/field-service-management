"""User entity for the identity bounded context."""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from fsm.identity.domain.errors import InvalidUser
from fsm.identity.domain.role import Role


@dataclass
class User:
    """Mutable entity representing an authenticated application user.

    Core responsibilities:
    - Holds the stable Google subject identifier linking this record to a Google account
    - Tracks the user's email, display name, and assigned role
    - Enforces construction invariants and role assignment

    google_sub is the immutable external identity key issued by Google; it never
    changes for a given Google account even if the email address is updated.
    """

    id: uuid.UUID
    google_sub: str
    email: str
    name: str
    role: Role

    def __post_init__(self) -> None:
        if not self.google_sub:
            raise InvalidUser("google_sub must not be empty.")
        if not self.email:
            raise InvalidUser("email must not be empty.")

    def assign_role(self, role: Role) -> None:
        """Set the user's role. Idempotent when the role is unchanged."""
        self.role = role
