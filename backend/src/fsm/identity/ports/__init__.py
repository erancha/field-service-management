"""Outbound port protocols for the identity bounded context.

Ports define the boundary between the domain and its infrastructure adapters.
All protocols are @runtime_checkable so adapters can be verified with isinstance
at startup or in tests.

Re-exported:
- VerifiedIdentity: frozen claims from a verified Google credential
- AuthPort: contract for verifying an external authentication credential
- UserRepository: persistence contract for User entities
"""

from fsm.identity.ports.auth import AuthPort, VerifiedIdentity
from fsm.identity.ports.repositories import UserRepository

__all__ = [
    "AuthPort",
    "UserRepository",
    "VerifiedIdentity",
]
