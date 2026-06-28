"""Resolve the Google OAuth callback URL for the sign-in and calendar-connect flows.

Each role is reached on its own localhost port (in Docker via the nginx edge, in host mode via its own
uvicorn), and Google accepts a loopback redirect URI only as localhost:<port>. The callback must
return to the port the flow began on, so the URL is derived from the incoming request by default; a
configured value overrides it for a fixed public (https) deployment.
"""
from __future__ import annotations

from starlette.requests import Request


def resolve_redirect_uri(request: Request, configured: str, callback_route: str) -> str:
    """Return the configured callback URL when set, else one derived from the request's own host."""
    return configured or str(request.url_for(callback_route))
