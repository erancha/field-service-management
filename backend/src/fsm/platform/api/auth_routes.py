"""FastAPI router for Google OAuth / session auth endpoints.

Wiring:
- GET  /auth/google/login    → redirect to Google authorization page (or 503 if unconfigured)
- GET  /auth/google/callback → exchange code, verify ID token, upsert user, set session
- GET  /auth/me              → return current session user or 401
- PATCH /auth/me             → update the caller's own profile (display_name, address, phone)
- POST /auth/logout          → clear the session

Injectable seams on app.state allow tests to bypass real Google without patching globals:
  app.state.token_exchange_override  — callable(flow, code) → the ID-token credential string
  app.state.auth_adapter_override    — AuthPort used instead of building GoogleOidcAuthAdapter
"""
from __future__ import annotations

import secrets
from typing import Callable

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse

from fsm.identity.adapters.repositories import SqlAlchemyUserRepository
from fsm.identity.application.identity_service import IdentityService, SignInHost
from fsm.identity.domain.errors import BackOfficeAccessDenied, NotFoundError
from fsm.identity.domain.phone import is_valid_phone
from fsm.identity.ports.auth import AuthPort
from fsm.platform.api.auth_deps import SessionUser, require_user
from fsm.platform.api.oauth_redirect import resolve_redirect_uri
from fsm.platform.api.oauth_token import fetch_token_relaxed
from fsm.platform.api.schemas import UpdateProfileRequest
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


def _build_flow(settings, redirect_uri: str):
    """Construct a google_auth_oauthlib Flow from in-memory client config."""
    from google_auth_oauthlib.flow import Flow

    client_config = {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret.get_secret_value(),
            "redirect_uris": [redirect_uri],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    flow = Flow.from_client_config(
        client_config,
        scopes=["openid", "email", "profile"],
        redirect_uri=redirect_uri,
    )
    return flow


def _real_token_exchange(flow, code: str) -> str:
    """Exchange the authorization code for tokens and return the raw ID-token credential."""
    fetch_token_relaxed(flow, code)
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

    redirect_uri = resolve_redirect_uri(request, settings.google_redirect_uri, "google_callback")
    flow = _build_flow(settings, redirect_uri)
    state = secrets.token_urlsafe(32)
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        state=state,
        include_granted_scopes="true",
    )
    request.session["oauth_state"] = state
    # authorization_url() mints a PKCE code_verifier and sends its derived challenge to Google. The
    # callback builds a separate Flow, so the verifier must ride the session to complete the exchange.
    request.session["code_verifier"] = flow.code_verifier
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

    redirect_uri = resolve_redirect_uri(request, settings.google_redirect_uri, "google_callback")
    flow = _build_flow(settings, redirect_uri)
    flow.code_verifier = request.session.get("code_verifier")
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
    request.session.pop("code_verifier", None)
    request.session["user_id"] = str(user.id)
    request.session["email"] = user.email
    return RedirectResponse("/", status_code=307)


_PROFILE_FIELDS = ("display_name", "address", "phone")


def _me_payload(user) -> dict:
    """JSON shape shared by GET and PATCH /auth/me."""
    return {
        "user_id": str(user.id),
        "email": user.email,
        "role": user.role.value,
        "role_status": user.role_status.value,
        "name": user.name,
        "display_name": user.display_name,
        "address": user.address,
        "phone": user.phone,
    }


@router.get("/me")
def auth_me(request: Request):
    """Return the caller's identity with role, status, and profile resolved from the database.

    The session carries only user_id; the live record is loaded per request so a just-approved
    technician or a just-edited profile is reflected without re-authenticating.
    """
    user_id = request.session.get("user_id")
    if not user_id:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    from uuid import UUID

    factory = _get_session_factory(request.app)
    with factory() as session:
        try:
            user = SqlAlchemyUserRepository(session).get(UUID(user_id))
        except (NotFoundError, ValueError):
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    return JSONResponse(_me_payload(user))


@router.patch("/me")
def update_me(
    body: UpdateProfileRequest,
    request: Request,
    session_user: SessionUser = Depends(require_user),
):
    """Update the caller's own profile fields.

    Identity comes only from the session (require_user); a field absent from the payload is
    left unchanged, a present field is stripped and stored, empty becoming NULL.
    """
    if "phone" in body.model_fields_set:
        phone = (body.phone or "").strip()
        if phone and not is_valid_phone(phone):
            return JSONResponse({"detail": "Invalid phone number"}, status_code=422)

    factory = _get_session_factory(request.app)
    with factory() as session:
        repo = SqlAlchemyUserRepository(session)
        user = repo.get(session_user.id)
        for field in _PROFILE_FIELDS:
            if field in body.model_fields_set:
                value = getattr(body, field)
                cleaned = value.strip() if value else ""
                setattr(user, field, cleaned or None)
        repo.save(user)
        session.commit()
    return JSONResponse(_me_payload(user))


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return JSONResponse({"status": "logged out"})
