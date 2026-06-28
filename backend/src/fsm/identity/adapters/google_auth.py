"""Google OIDC authentication adapter for the identity bounded context."""
from __future__ import annotations

from typing import Callable

import google.auth.transport.requests
import google.oauth2.id_token
from google.auth.exceptions import GoogleAuthError

from fsm.identity.domain.errors import AuthenticationError
from fsm.identity.ports.auth import VerifiedIdentity


# Google signs ID tokens against its own clock, so a host running slightly behind would otherwise
# reject a freshly issued token as "used too early". A few seconds of leeway absorbs ordinary clock
# drift without materially widening the token's validity window.
_CLOCK_SKEW_SECONDS = 10


def _default_verify(credential: str, client_id: str) -> dict:
    return google.oauth2.id_token.verify_oauth2_token(
        credential,
        google.auth.transport.requests.Request(),
        client_id,
        clock_skew_in_seconds=_CLOCK_SKEW_SECONDS,
    )


class GoogleOidcAuthAdapter:
    """AuthPort adapter that verifies Google OIDC ID tokens.

    The verifier callable is injectable so unit tests can supply a fake without
    touching the network or issuing real Google tokens.
    """

    def __init__(
        self,
        client_id: str,
        verify_token: Callable[[str, str], dict] = _default_verify,
    ) -> None:
        if not client_id:
            raise ValueError("client_id must be a non-empty string; an empty audience disables audience checking")
        self._client_id = client_id
        self._verify_token = verify_token

    def verify(self, credential: str) -> VerifiedIdentity:
        """Verify a Google ID token and return the extracted identity claims.

        Raises AuthenticationError when the token is invalid, expired, or missing
        required claims. Lets any other exception propagate so transport faults
        and programming errors are not silently mislabelled as auth failures.
        """
        try:
            claims = self._verify_token(credential, self._client_id)
        except (ValueError, GoogleAuthError) as exc:
            raise AuthenticationError(f"Token verification failed: {exc}") from exc

        if claims.get("email_verified") is not True:
            raise AuthenticationError("Token claims do not include a verified email (email_verified must be true)")

        for claim in ("sub", "email", "name"):
            if not claims.get(claim):
                raise AuthenticationError(f"Missing required claim: {claim!r}")

        return VerifiedIdentity(
            google_sub=claims["sub"],
            email=claims["email"],
            name=claims["name"],
        )
