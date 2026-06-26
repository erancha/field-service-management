"""Auth port definition for the identity bounded context.

Defines the boundary between the domain and any external authentication provider
(e.g. Google OIDC). Concrete adapters implement AuthPort without the domain
depending on them.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from fsm.identity.domain.errors import AuthenticationError

__all__ = ["AuthenticationError", "AuthPort", "VerifiedIdentity"]


@dataclass(frozen=True)
class VerifiedIdentity:
    """Immutable value object holding the claims extracted from a verified credential.

    Produced by AuthPort.verify; consumed by the sign-in use-case to look up or
    create the corresponding User record.
    """

    google_sub: str
    email: str
    name: str


@runtime_checkable
class AuthPort(Protocol):
    """Contract for verifying an external authentication credential.

    Concrete adapters call the identity provider (Google OIDC token endpoint,
    a local stub, etc.) and return a VerifiedIdentity on success.
    """

    def verify(self, credential: str) -> VerifiedIdentity:
        """Verify the credential and return the extracted identity claims.

        Raises AuthenticationError when the credential is invalid, expired, or
        cannot be verified against the provider.
        """
        ...
