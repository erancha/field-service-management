"""Application layer for the identity bounded context.

Orchestrates domain operations against the port interfaces, keeping
infrastructure adapters out of business logic. One service is provided:

- IdentityService: resolves Google credentials to User records, handles host-aware
  first-time account creation, claim synchronisation, and technician approval
- SignInHost: the deployment a sign-in arrives on, which drives role assignment
"""

from fsm.identity.application.identity_service import (
    IdentityService,
    SignInHost,
    SignInOutcome,
)

__all__ = ["IdentityService", "SignInHost", "SignInOutcome"]
