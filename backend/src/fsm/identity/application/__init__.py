"""Application layer for the identity bounded context.

Orchestrates domain operations against the port interfaces, keeping
infrastructure adapters out of business logic. One service is provided:

- IdentityService: resolves Google credentials to User records, handles
  first-time account creation, claim synchronisation, and role assignment
"""

from fsm.identity.application.identity_service import IdentityService

__all__ = ["IdentityService"]
