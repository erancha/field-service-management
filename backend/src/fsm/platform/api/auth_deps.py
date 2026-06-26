"""Session-auth dependencies for the API layer.

require_user resolves the signed session (populated by the OIDC callback in auth_routes)
into a SessionUser, or raises 401. require_role additionally enforces the caller's role.
These gate the scheduling API so identity always comes from the session, never from the
request body — a client cannot act as another user by passing an id.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status

from fsm.identity.domain.role import Role


@dataclass(frozen=True)
class SessionUser:
    """Authenticated caller derived from the signed session cookie."""

    id: UUID
    role: Role
    email: str | None


def require_user(request: Request) -> SessionUser:
    """Resolve the authenticated session user, or raise 401.

    A missing SessionMiddleware (no SESSION_SECRET configured) leaves no session in
    scope; that is treated as unauthenticated so an unconfigured deployment fails
    closed rather than raising on session access.
    """
    session = request.scope.get("session")
    if not session or not session.get("user_id"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    try:
        return SessionUser(
            id=UUID(session["user_id"]),
            role=Role(session["role"]),
            email=session.get("email"),
        )
    except (ValueError, KeyError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")


def require_role(*allowed: Role):
    """Return a dependency requiring an authenticated user whose role is one of `allowed`."""

    def _dep(user: SessionUser = Depends(require_user)) -> SessionUser:
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role for this action"
            )
        return user

    return _dep
