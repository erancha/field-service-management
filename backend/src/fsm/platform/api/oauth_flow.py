"""Shared skeleton of the Google OAuth authorization-code flows.

The sign-in and calendar-connect routers run the same choreography: build a Flow from
in-memory client config, redirect to Google with a fresh CSRF state and a PKCE verifier
stashed in the session, then in the callback validate the state, restore the verifier onto a
newly built Flow, and exchange the code. This module owns that skeleton; each router keeps
only its flow-specific parameters — scopes, session-key prefix, credential attribute, and the
app.state override attribute for its token-exchange test seam.

Session keys are namespaced by prefix ("" for sign-in, "calendar_" for calendar connect) so
both flows can be in progress in one browser session without clobbering each other.
"""
from __future__ import annotations

import secrets
from typing import Callable, Sequence

from fastapi import Request
from fastapi.responses import RedirectResponse

from fsm.platform.api.oauth_token import fetch_token_relaxed
from fsm.shared.google_oauth import GOOGLE_AUTH_URI, GOOGLE_TOKEN_URI


def _state_key(session_prefix: str) -> str:
    return f"{session_prefix}oauth_state"


def _verifier_key(session_prefix: str) -> str:
    return f"{session_prefix}code_verifier"


def build_flow(settings, redirect_uri: str, scopes: Sequence[str]):
    """Construct a google_auth_oauthlib Flow from in-memory client config for the given scopes."""
    from google_auth_oauthlib.flow import Flow

    client_config = {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret.get_secret_value(),
            "redirect_uris": [redirect_uri],
            "auth_uri": GOOGLE_AUTH_URI,
            "token_uri": GOOGLE_TOKEN_URI,
        }
    }
    return Flow.from_client_config(
        client_config,
        scopes=list(scopes),
        redirect_uri=redirect_uri,
    )


def begin_authorization(
    request: Request, flow, session_prefix: str, **authorization_url_params
) -> RedirectResponse:
    """Mint the CSRF state, stash it and the PKCE verifier in the session, redirect to Google.

    authorization_url() mints a PKCE code_verifier and sends its derived challenge to Google.
    The callback builds a separate Flow, so the verifier must ride the session to complete the
    exchange. Extra keyword params (e.g. prompt="consent") pass through to authorization_url().
    """
    state = secrets.token_urlsafe(32)
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        state=state,
        include_granted_scopes="true",
        **authorization_url_params,
    )
    request.session[_state_key(session_prefix)] = state
    request.session[_verifier_key(session_prefix)] = flow.code_verifier
    return RedirectResponse(auth_url, status_code=307)


def state_matches(request: Request, state: str, session_prefix: str) -> bool:
    """Constant-time check of the callback state against the one minted at login."""
    expected = request.session.get(_state_key(session_prefix))
    return isinstance(expected, str) and bool(expected) and secrets.compare_digest(expected, state)


def restore_code_verifier(flow, request: Request, session_prefix: str) -> None:
    """Put the PKCE verifier minted at login onto the callback's freshly built Flow."""
    flow.code_verifier = request.session.get(_verifier_key(session_prefix))


def clear_flow_session(request: Request, session_prefix: str) -> None:
    """Drop the one-shot state and verifier; runs on success and on controlled rejection."""
    request.session.pop(_state_key(session_prefix), None)
    request.session.pop(_verifier_key(session_prefix), None)


def make_token_exchange(credential_attribute: str) -> Callable:
    """Build the real token exchange returning one credential field (id_token, refresh_token)."""

    def exchange(flow, code: str) -> str:
        fetch_token_relaxed(flow, code)
        return getattr(flow.credentials, credential_attribute)

    return exchange


def resolve_token_exchange(app, override_attribute: str, default: Callable) -> Callable:
    """Prefer the app.state test seam over the real Google exchange."""
    override = getattr(app.state, override_attribute, None)
    return override if override is not None else default


def get_session_factory(app):
    """Return the app's session factory, building it lazily from settings if absent."""
    from fsm.platform.app import _get_session_factory as _lazy

    return _lazy(app)


def get_settings(request: Request):
    """Return the Settings attached to the app state, or the process singleton.

    Imported lazily so tests that monkeypatch fsm.platform.config.get_settings are honored.
    """
    settings = getattr(request.app.state, "settings", None)
    if settings is not None:
        return settings
    from fsm.platform.config import get_settings as process_settings

    return process_settings()
