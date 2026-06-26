"""Auth-error detection for calendar operations.

Provides is_auth_error — a duck-typed predicate that identifies revoked or
expired OAuth credentials without importing google-auth directly, so the
platform layer stays free of calendar-context imports.
"""
from __future__ import annotations


def is_auth_error(exc: Exception) -> bool:
    """Return True when exc indicates a revoked or expired calendar credential.

    Three conditions are checked (any one is sufficient):
    - The exception's type name is "RefreshError" (google.auth.exceptions.RefreshError).
    - "invalid_grant" appears in the stringified exception (OAuth error payload).
    - The exception exposes an HTTP response with status 401 via exc.resp.status.

    Duck-typed so neither google-auth nor googleapiclient needs to be imported here.
    """
    if type(exc).__name__ == "RefreshError":
        return True
    if "invalid_grant" in str(exc):
        return True
    resp = getattr(exc, "resp", None)
    if getattr(resp, "status", None) == 401:
        return True
    return False
