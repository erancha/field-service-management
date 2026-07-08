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

import contextlib
import os


@contextlib.contextmanager
def _relaxed_token_scope():
    """Set OAUTHLIB_RELAX_TOKEN_SCOPE for the enclosed block, restoring the prior value after.

    oauthlib reads the flag at exchange time, so scoping it to the exchange keeps the relaxation
    from leaking to unrelated OAuth exchanges elsewhere in the process while the check stays in
    force for them.
    """
    previous = os.environ.get("OAUTHLIB_RELAX_TOKEN_SCOPE")
    os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("OAUTHLIB_RELAX_TOKEN_SCOPE", None)
        else:
            os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = previous


def fetch_token_relaxed(flow, code: str) -> None:
    """Exchange the authorization code on the flow, tolerating Google's scope normalisation.

    Relaxes oauthlib's granted-vs-requested scope check only for the duration of the exchange, then
    completes it in place; callers read flow.credentials afterwards.
    """
    with _relaxed_token_scope():
        flow.fetch_token(code=code)
