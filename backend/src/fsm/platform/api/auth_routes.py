"""FastAPI router for Google OAuth / session auth endpoints.

Wiring:
- GET  /auth/google/login    → redirect to Google authorization page (or 503 if unconfigured)
- GET  /auth/google/callback → exchange code, verify ID token, upsert user, set session
- GET  /auth/me              → return current session user or 401
- POST /auth/logout          → clear the session

Injectable seams on app.state allow tests to bypass real Google without patching globals:
  app.state.token_exchange_override  — callable(flow, code) → the ID-token credential string
  app.state.auth_adapter_override    — AuthPort used instead of building GoogleOidcAuthAdapter
"""
from __future__ import annotations

import secrets
from typing import Callable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from fsm.identity.adapters.repositories import SqlAlchemyUserRepository
from fsm.identity.application.identity_service import IdentityService, SignInHost
from fsm.identity.domain.errors import BackOfficeAccessDenied
from fsm.identity.ports.auth import AuthPort
from fsm.platform.api.auth_deps import resolve_current_user
from fsm.platform.events import ADMINS_CHANNEL, publish_to_app

router = APIRouter(prefix="/auth")

_HOST_BY_ROLE = {
    "customer": SignInHost.CUSTOMER,
    "technician": SignInHost.TECHNICIAN,
    "backoffice": SignInHost.BACKOFFICE,
}


def _sign_in_host(settings) -> SignInHost:
    """Map the process FSM_ROLE to the sign-in host; unknown roles default to the customer funnel."""
    return _HOST_BY_ROLE.get(settings.fsm_role, SignInHost.CUSTOMER)


_publish = publish_to_app


def _build_flow(settings):
    """Construct a google_auth_oauthlib Flow from in-memory client config."""
    from google_auth_oauthlib.flow import Flow

    client_config = {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret.get_secret_value(),
            "redirect_uris": [settings.google_redirect_uri],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    flow = Flow.from_client_config(
        client_config,
        scopes=["openid", "email", "profile"],
        redirect_uri=settings.google_redirect_uri,
    )
    return flow


def _real_token_exchange(flow, code: str) -> str:
    """Exchange the authorization code for tokens and return the raw ID-token credential."""
    flow.fetch_token(code=code)
    return flow.credentials.id_token  # type: ignore[attr-defined]


def _get_token_exchange(app) -> Callable:
    override = getattr(app.state, "token_exchange_override", None)
    return override if override is not None else _real_token_exchange


def _get_auth_adapter(app, settings) -> AuthPort:
    override = getattr(app.state, "auth_adapter_override", None)
    if override is not None:
        return override
    from fsm.identity.adapters.google_auth import GoogleOidcAuthAdapter

    return GoogleOidcAuthAdapter(client_id=settings.google_client_id)


def _get_session_factory(app):
    from fsm.platform.app import _get_session_factory as _lazy

    return _lazy(app)


def _get_settings(request: Request):
    return getattr(request.app.state, "settings", None) or __import__(
        "fsm.platform.config", fromlist=["get_settings"]
    ).get_settings()


@router.get("/google/login")
def google_login(request: Request):
    settings = _get_settings(request)
    if not settings.google_client_id or not settings.google_client_secret:
        return JSONResponse(
            {"detail": "Google sign-in not configured"},
            status_code=503,
        )

    flow = _build_flow(settings)
    state = secrets.token_urlsafe(32)
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        state=state,
        include_granted_scopes="true",
    )
    request.session["oauth_state"] = state
    return RedirectResponse(auth_url, status_code=307)


@router.get("/google/callback")
async def google_callback(request: Request, code: str = "", state: str = ""):
    settings = _get_settings(request)

    expected_state = request.session.get("oauth_state")
    if not expected_state or not secrets.compare_digest(expected_state, state):
        return JSONResponse({"detail": "Invalid or missing state parameter"}, status_code=400)

    token_exchange = _get_token_exchange(request.app)
    auth_adapter = _get_auth_adapter(request.app, settings)

    if not settings.google_client_id or not settings.google_client_secret:
        return JSONResponse({"detail": "Google sign-in not configured"}, status_code=503)

    flow = _build_flow(settings)
    id_token = token_exchange(flow, code)

    host = _sign_in_host(settings)
    factory = _get_session_factory(request.app)
    with factory() as session:
        svc = IdentityService(auth=auth_adapter, users=SqlAlchemyUserRepository(session))
        try:
            outcome = svc.sign_in(id_token, host=host, admin_emails=settings.admin_email_set)
        except BackOfficeAccessDenied:
            session.rollback()
            return JSONResponse({"detail": "Not authorised for the back office"}, status_code=403)
        session.commit()

    user = outcome.user
    if outcome.requested_pending:
        await _publish(
            request.app,
            ADMINS_CHANNEL,
            {
                "type": "technician_access.requested",
                "user_id": str(user.id),
                "email": user.email,
                "name": user.name,
            },
        )
    elif outcome.withdrew_pending:
        await _publish(
            request.app,
            ADMINS_CHANNEL,
            {"type": "technician_access.withdrawn", "user_id": str(user.id)},
        )

    request.session.pop("oauth_state", None)
    request.session["user_id"] = str(user.id)
    request.session["email"] = user.email
    return RedirectResponse("/", status_code=307)


@router.get("/me")
def auth_me(request: Request):
    """Return the caller's identity with role and status resolved from the database.

    The session carries only user_id; the live role/status come from the current user record so a
    just-approved technician sees their new status without re-authenticating.
    """
    user_id = request.session.get("user_id")
    if not user_id:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    from uuid import UUID

    factory = _get_session_factory(request.app)
    with factory() as session:
        try:
            current = resolve_current_user(UUID(user_id), SqlAlchemyUserRepository(session))
        except Exception:
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    return JSONResponse(
        {
            "user_id": str(current.id),
            "email": current.email,
            "role": current.role.value,
            "role_status": current.role_status.value,
        }
    )


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return JSONResponse({"status": "logged out"})
