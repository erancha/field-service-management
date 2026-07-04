"""Shared authorization-code exchange for the sign-in and calendar-connect OAuth flows.

Both flows request one scope set but receive a different granted set: Google normalises OIDC scopes
(email -> .../userinfo.email, profile -> .../userinfo.profile, reordered with openid) and, under
incremental authorization (include_granted_scopes=true), folds the already-granted sign-in scopes
into every later grant. Either way the granted set never byte-matches the requested set, and oauthlib
treats any granted-vs-requested mismatch as fatal unless OAUTHLIB_RELAX_TOKEN_SCOPE is set. Routing
both exchanges through here makes the relaxation self-contained per flow, so neither depends on the
other having run first in the same process.
"""
from __future__ import annotations

import os


def fetch_token_relaxed(flow, code: str) -> None:
    """Exchange the authorization code on the flow, tolerating Google's scope normalisation.

    Sets OAUTHLIB_RELAX_TOKEN_SCOPE before the exchange so oauthlib accepts the granted-vs-requested
    scope mismatch, then completes the exchange in place; callers read flow.credentials afterwards.
    """
    os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")
    flow.fetch_token(code=code)
