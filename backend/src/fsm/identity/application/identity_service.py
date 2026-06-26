"""Use-case orchestration for the identity bounded context."""
from __future__ import annotations

from typing import Callable
from uuid import UUID, uuid4

from fsm.identity.domain.errors import DuplicateGoogleSub
from fsm.identity.domain.role import Role
from fsm.identity.domain.user import User
from fsm.identity.ports.auth import AuthPort
from fsm.identity.ports.repositories import UserRepository


class IdentityService:
    """Orchestrates sign-in and role-assignment for the identity bounded context.

    Core responsibilities:
    - Resolves a Google credential to an existing or newly-created User record
    - Keeps email and display name in sync with the latest verified claims
    - Delegates persistence to the injected UserRepository and auth to AuthPort
    """

    def __init__(
        self,
        auth: AuthPort,
        users: UserRepository,
        new_id: Callable[[], UUID] = uuid4,
    ) -> None:
        self._auth = auth
        self._users = users
        self._new_id = new_id

    def sign_in_with_google(self, credential: str) -> User:
        """Verify a Google credential and return the corresponding User.

        Creates a new CUSTOMER user on first sign-in. On subsequent sign-ins,
        updates email and name from the latest verified claims if they changed.
        A concurrent first-sign-in race (DuplicateGoogleSub from the repository)
        resolves to a normal login by re-fetching the user committed by the winner.
        Propagates AuthenticationError when the credential is invalid or expired.
        """
        identity = self._auth.verify(credential)
        user = self._users.get_by_google_sub(identity.google_sub)
        if user is None:
            user = User(
                id=self._new_id(),
                google_sub=identity.google_sub,
                email=identity.email,
                name=identity.name,
                role=Role.CUSTOMER,
            )
            try:
                self._users.add(user)
            except DuplicateGoogleSub:
                user = self._users.get_by_google_sub(identity.google_sub)
        else:
            if user.email != identity.email or user.name != identity.name:
                user.email = identity.email
                user.name = identity.name
                self._users.save(user)
        return user

    def assign_role(self, user_id: UUID, role: Role) -> User:
        """Assign a role to an existing user and persist the change.

        Propagates NotFoundError when no user with user_id exists.
        """
        user = self._users.get(user_id)
        user.assign_role(role)
        self._users.save(user)
        return user
