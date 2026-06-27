"""Pure domain layer for the identity bounded context.

Manages users and roles for Google OIDC-authenticated accounts. This layer has
no I/O, no persistence, and no dependency outside the Python standard library.

Public types re-exported here:
- Role: CUSTOMER, TECHNICIAN, and ADMIN role enum
- RoleStatus: PENDING / APPROVED / REJECTED approval state of a role
- User: authenticated user entity with role transitions
- IdentityError, InvalidUser: error hierarchy
"""

from fsm.identity.domain.errors import AuthenticationError, DuplicateGoogleSub, IdentityError, InvalidUser, NotFoundError
from fsm.identity.domain.role import Role
from fsm.identity.domain.role_status import RoleStatus
from fsm.identity.domain.user import User

__all__ = [
    "AuthenticationError",
    "DuplicateGoogleSub",
    "IdentityError",
    "InvalidUser",
    "NotFoundError",
    "Role",
    "RoleStatus",
    "User",
]
