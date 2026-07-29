"""FastAPI router for the back-office technician-approval queue (ADMIN only).

Endpoints list pending technician requests and approve or reject them. Each decision resolves the
target user, records the deciding administrator, and publishes a `technician_access.decided` event
to the requester's channel so their waiting screen updates live. The queue is exactly the users in
TECHNICIAN/PENDING, so no separate request entity is needed.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from fsm.identity.adapters.repositories import SqlAlchemyUserRepository
from fsm.identity.application.identity_service import IdentityService
from fsm.identity.domain.errors import InvalidRoleDecision, NotFoundError
from fsm.identity.domain.role import Role
from fsm.platform.api.auth_deps import SessionUser, require_role
from fsm.platform.events import publish_to_app, user_channel

router = APIRouter(prefix="/api/back-office")


def _session_factory(request: Request):
    from fsm.platform.app import _get_session_factory

    return _get_session_factory(request.app)


@router.get("/technician-requests")
def list_technician_requests(
    request: Request, admin: SessionUser = Depends(require_role(Role.ADMIN))
) -> list[dict]:
    """List technicians awaiting approval — the back-office queue."""
    with _session_factory(request)() as session:
        svc = IdentityService(users=SqlAlchemyUserRepository(session))
        return [
            {"user_id": str(u.id), "email": u.email, "name": u.name}
            for u in svc.list_pending_technicians()
        ]


@router.post("/technician-requests/{user_id}/approve")
async def approve_technician_request(
    user_id: UUID, request: Request, admin: SessionUser = Depends(require_role(Role.ADMIN))
) -> dict:
    """Approve a pending technician and notify them live."""
    return await _decide(request, user_id, admin, approve=True)


@router.post("/technician-requests/{user_id}/reject")
async def reject_technician_request(
    user_id: UUID, request: Request, admin: SessionUser = Depends(require_role(Role.ADMIN))
) -> dict:
    """Reject a pending technician and notify them live."""
    return await _decide(request, user_id, admin, approve=False)


async def _decide(request: Request, user_id: UUID, admin: SessionUser, approve: bool) -> dict:
    with _session_factory(request)() as session:
        svc = IdentityService(users=SqlAlchemyUserRepository(session))
        try:
            if approve:
                user = svc.approve_technician(user_id, decided_by=admin.id)
            else:
                user = svc.reject_technician(user_id, decided_by=admin.id)
        except NotFoundError:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such user")
        except InvalidRoleDecision as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
        session.commit()

    decision = "approved" if approve else "rejected"
    await publish_to_app(
        request.app,
        user_channel(user.id),
        {
            "type": "technician_access.decided",
            "decision": decision,
            "user_id": str(user.id),
            "role": user.role.value,
            "role_status": user.role_status.value,
        },
    )
    return {"user_id": str(user.id), "role": user.role.value, "role_status": user.role_status.value}
