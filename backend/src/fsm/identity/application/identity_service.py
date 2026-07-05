"""Use-case orchestration for the identity bounded context."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import Enum
from typing import Callable
from uuid import UUID, uuid4

from fsm.identity.domain.errors import (
    BackOfficeAccessDenied,
    DuplicateGoogleSub,
    InvalidRoleDecision,
)
from fsm.identity.domain.role import Role
from fsm.identity.domain.role_status import RoleStatus
from fsm.identity.domain.user import User
from fsm.identity.ports.auth import AuthPort, VerifiedIdentity
from fsm.identity.ports.repositories import UserRepository


class SignInHost(str, Enum):
    """Deployment a sign-in arrives on; determines the role and status assigned.

    CUSTOMER grants customer access outright, TECHNICIAN requests technician access pending
    approval, BACKOFFICE grants ADMIN only to the configured allowlist and refuses everyone else.
    """

    CUSTOMER = "CUSTOMER"
    TECHNICIAN = "TECHNICIAN"
    BACKOFFICE = "BACKOFFICE"


@dataclass(frozen=True)
class SignInOutcome:
    """Result of a sign-in: the resolved user and what the back-office queue should reflect.

    requested_pending is True when this sign-in newly placed the user in TECHNICIAN/PENDING (a row
    to add to the approval queue); withdrew_pending is True when it moved them out of a prior
    TECHNICIAN/PENDING (a row to remove). Both are False for an unchanged sign-in.
    """

    user: User
    requested_pending: bool
    withdrew_pending: bool


def _is_pending_technician(role: Role, status: RoleStatus) -> bool:
    return role is Role.TECHNICIAN and status is RoleStatus.PENDING


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class IdentityService:
    """Orchestrates host-aware sign-in and technician approval for the identity context.

    Core responsibilities:
    - Resolves a Google credential to an existing or newly-created User record
    - Assigns role and approval status from the host the sign-in arrived on
    - Records back-office approve/reject decisions on pending technicians

    Sign-in is the only path that creates users; the host the process serves expresses the
    person's intent, so signing in on a different host reassigns the role accordingly.
    """

    def __init__(
        self,
        users: UserRepository,
        auth: AuthPort | None = None,
        new_id: Callable[[], UUID] = uuid4,
        now: Callable[[], dt.datetime] = _utc_now,
    ) -> None:
        self._auth = auth
        self._users = users
        self._new_id = new_id
        self._now = now

    def sign_in(
        self, credential: str, host: SignInHost, admin_emails: frozenset[str]
    ) -> SignInOutcome:
        """Verify a Google credential and assign the user for the sign-in host.

        Creates the user on first sign-in. The host decides the assignment (see _apply_host),
        which also reassigns an existing user — so a person who signs in on a different host is
        moved to that host's role. Email and name are kept in sync with the latest claims, and a
        concurrent first-sign-in race resolves to the winner's record. Raises BackOfficeAccessDenied
        when a back-office sign-in is not on admin_emails (no user is created in that case). The
        returned outcome reports whether the back-office queue gained or lost a pending request.
        """
        assert self._auth is not None, "sign_in requires an AuthPort; approval-only flows omit it"
        identity = self._auth.verify(credential)
        user = self._users.get_by_google_sub(identity.google_sub)
        if user is None:
            user = User(
                id=self._new_id(),
                google_sub=identity.google_sub,
                email=identity.email,
                name=identity.name,
                role=Role.CUSTOMER,
                role_status=RoleStatus.APPROVED,
            )
            self._apply_host(user, host, admin_emails)
            try:
                self._users.add(user)
            except DuplicateGoogleSub:
                user = self._users.get_by_google_sub(identity.google_sub)
                assert user is not None, "DuplicateGoogleSub means the winning row exists"
                return self._reconcile_existing(user, identity, host, admin_emails)
            return SignInOutcome(
                user=user,
                requested_pending=_is_pending_technician(user.role, user.role_status),
                withdrew_pending=False,
            )

        return self._reconcile_existing(user, identity, host, admin_emails)

    def list_pending_technicians(self) -> list[User]:
        """Return technicians awaiting approval — the back-office approval queue."""
        return self._users.list_pending_technicians()

    def approve_technician(self, user_id: UUID, decided_by: UUID) -> User:
        """Approve a pending technician, recording the deciding administrator and time.

        Raises NotFoundError when no such user exists, InvalidRoleDecision when the target is not
        a pending technician.
        """
        user = self._users.get(user_id)
        self._assert_pending_technician(user)
        user.approve(decided_by=decided_by, at=self._now())
        self._users.save(user)
        return user

    def reject_technician(self, user_id: UUID, decided_by: UUID) -> User:
        """Reject a pending technician, recording the deciding administrator and time.

        Raises NotFoundError when no such user exists, InvalidRoleDecision when the target is not
        a pending technician.
        """
        user = self._users.get(user_id)
        self._assert_pending_technician(user)
        user.reject(decided_by=decided_by, at=self._now())
        self._users.save(user)
        return user

    def _reconcile_existing(
        self,
        user: User,
        identity: VerifiedIdentity,
        host: SignInHost,
        admin_emails: frozenset[str],
    ) -> SignInOutcome:
        """Sync claims and re-apply host assignment to an existing user, saving only on change."""
        was_pending = _is_pending_technician(user.role, user.role_status)
        before = (user.email, user.name, user.role, user.role_status)
        if user.email != identity.email or user.name != identity.name:
            user.email = identity.email
            user.name = identity.name
        self._apply_host(user, host, admin_emails)
        after = (user.email, user.name, user.role, user.role_status)
        if before != after:
            self._users.save(user)
        is_pending = _is_pending_technician(user.role, user.role_status)
        return SignInOutcome(
            user=user,
            requested_pending=is_pending and not was_pending,
            withdrew_pending=was_pending and not is_pending,
        )

    def _apply_host(
        self, user: User, host: SignInHost, admin_emails: frozenset[str]
    ) -> None:
        """Set the user's role/status from the sign-in host.

        Technician access is sticky once claimed: a user already on the TECHNICIAN role keeps their
        current status (pending stays pending, approved stays approved, rejected is not re-queued).
        The back-office host grants ADMIN only to the allowlist and refuses everyone else.
        """
        if host is SignInHost.CUSTOMER:
            user.grant_role(Role.CUSTOMER)
        elif host is SignInHost.TECHNICIAN:
            if user.role is not Role.TECHNICIAN:
                user.request_role(Role.TECHNICIAN)
        elif host is SignInHost.BACKOFFICE:
            if user.email.lower() in admin_emails:
                user.grant_role(Role.ADMIN)
            else:
                raise BackOfficeAccessDenied(
                    f"{user.email} is not authorised for the back office"
                )

    @staticmethod
    def _assert_pending_technician(user: User) -> None:
        if user.role is not Role.TECHNICIAN or user.role_status is not RoleStatus.PENDING:
            raise InvalidRoleDecision(
                f"User {user.id!r} is not a pending technician "
                f"(role={user.role.value}, status={user.role_status.value})"
            )
