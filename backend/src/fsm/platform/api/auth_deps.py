"""Session-auth dependencies for the API layer.

The signed session cookie carries only the user's identity (user_id). require_user looks the
current role and approval status up from the database on every request, so an administrator's
approval or revocation takes effect immediately rather than waiting for the cookie to expire.
require_role additionally requires the role to be APPROVED. Identity always comes from the session,
never from the request body — a client cannot act as another user by passing an id.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status

from fsm.identity.domain.errors import NotFoundError
from fsm.identity.domain.role import Role
from fsm.identity.domain.role_status import RoleStatus
from fsm.identity.ports.repositories import UserRepository


@dataclass(frozen=True)
class SessionUser:
    """Authenticated caller, with role and approval status resolved from the database.

    role_status defaults to APPROVED so that test fixtures overriding require_user (which supply a
    role directly) describe an effective user without having to name the status explicitly.
    """

    id: UUID
    role: Role
    email: str | None
    role_status: RoleStatus = RoleStatus.APPROVED


def resolve_current_user(user_id: UUID, users: UserRepository) -> SessionUser:
    """Build a SessionUser from the user's current persisted role and status.

    Raises 401 when the id has no user — a stale session whose account no longer exists.
    """
    try:
        user = users.get(user_id)
    except NotFoundError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Session user no longer exists"
        )
    return SessionUser(
        id=user.id, role=user.role, email=user.email, role_status=user.role_status
    )


def require_user(request: Request) -> SessionUser:
    """Resolve the authenticated caller from the session id and the database, or raise 401.

    A missing SessionMiddleware (no SESSION_SECRET configured) leaves no session in scope; that is
    treated as unauthenticated so an unconfigured deployment fails closed.
    """
    session = request.scope.get("session")
    if not session or not session.get("user_id"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    try:
        user_id = UUID(session["user_id"])
    except (ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")

    from fsm.identity.adapters.repositories import SqlAlchemyUserRepository
    from fsm.platform.app import _get_session_factory

    factory = _get_session_factory(request.app)
    with factory() as db:
        return resolve_current_user(user_id, SqlAlchemyUserRepository(db))


def require_role(*allowed: Role):
    """Return a dependency requiring an authenticated user with an APPROVED role in `allowed`.

    A pending or rejected status fails even when the role itself matches, so a technician awaiting
    approval cannot reach technician endpoints.
    """

    def _dep(user: SessionUser = Depends(require_user)) -> SessionUser:
        if user.role not in allowed or user.role_status is not RoleStatus.APPROVED:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role for this action"
            )
        return user

    return _dep
