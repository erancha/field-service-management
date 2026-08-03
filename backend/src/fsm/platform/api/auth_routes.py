"""FastAPI router for Google OAuth / session auth endpoints.

Wiring:
- GET  /auth/google/login    → redirect to Google authorization page (or 503 if unconfigured)
- GET  /auth/google/callback → exchange code, verify ID token, upsert user, set session
- GET  /auth/me              → return current session user or 401
- PATCH /auth/me             → update the caller's own profile (display_name, address, phone)
- POST /auth/me/assist-disclaimer → record that the caller accepted the assistant disclaimer
- POST /auth/logout          → clear the session

Injectable seams on app.state allow tests to bypass real Google without patching globals:
  app.state.token_exchange_override  — callable(flow, code) → the ID-token credential string
  app.state.auth_adapter_override    — AuthPort used instead of building GoogleOidcAuthAdapter
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse

from fsm.identity.adapters.repositories import SqlAlchemyUserRepository
from fsm.identity.application.identity_service import IdentityService, SignInHost
from fsm.identity.domain.errors import BackOfficeAccessDenied, NotFoundError
from fsm.identity.domain.phone import is_valid_phone
from fsm.identity.ports.auth import AuthPort
from fsm.platform.api.auth_deps import SessionUser, require_user
from fsm.platform.api.oauth_flow import (
    begin_authorization,
    build_flow,
    clear_flow_session,
    get_session_factory,
    get_settings,
    make_token_exchange,
    resolve_token_exchange,
    restore_code_verifier,
    state_matches,
)
from fsm.platform.admin_alerts import send_technician_access_requested
from fsm.platform.api.oauth_redirect import resolve_redirect_uri
from fsm.platform.api.schemas import UpdateProfileRequest
from fsm.platform.events import ADMINS_CHANNEL, publish_to_app
from fsm.platform.notifications_factory import build_email_sender
from fsm.platform.roles import DEPLOYMENTS

router = APIRouter(prefix="/auth")


def _sign_in_host(settings) -> SignInHost:
    """Return the sign-in funnel of the role this process serves."""
    host = DEPLOYMENTS[settings.fsm_role].sign_in_host
    # These routes exist only inside an app, and no app is built for a role without a funnel.
    assert host is not None
    return host


_publish = publish_to_app


# Sign-in owns the unprefixed oauth session keys (oauth_state, code_verifier).
_SESSION_PREFIX = ""

_OIDC_SCOPES = ("openid", "email", "profile")

# The exchanged credential is the raw ID token; the sign-in service verifies and decodes it.
_real_token_exchange = make_token_exchange("id_token")


def _build_flow(settings, redirect_uri: str):
    """Construct the sign-in Flow, requesting only the OIDC identity scopes."""
    return build_flow(settings, redirect_uri, scopes=_OIDC_SCOPES)


def _get_auth_adapter(app, settings) -> AuthPort:
    override = getattr(app.state, "auth_adapter_override", None)
    if override is not None:
        return override
    from fsm.identity.adapters.google_auth import GoogleOidcAuthAdapter

    return GoogleOidcAuthAdapter(client_id=settings.google_client_id)


@router.get("/google/login")
def google_login(request: Request):
    settings = get_settings(request)
    if not settings.google_client_id or not settings.google_client_secret:
        return JSONResponse(
            {"detail": "Google sign-in not configured"},
            status_code=503,
        )

    redirect_uri = resolve_redirect_uri(request, settings.google_redirect_uri, "google_callback")
    flow = _build_flow(settings, redirect_uri)
    return begin_authorization(request, flow, _SESSION_PREFIX)


@router.get("/google/callback")
async def google_callback(request: Request, code: str = "", state: str = ""):
    settings = get_settings(request)

    if not state_matches(request, state, _SESSION_PREFIX):
        return JSONResponse({"detail": "Invalid or missing state parameter"}, status_code=400)

    token_exchange = resolve_token_exchange(
        request.app, "token_exchange_override", _real_token_exchange
    )
    auth_adapter = _get_auth_adapter(request.app, settings)

    if not settings.google_client_id or not settings.google_client_secret:
        return JSONResponse({"detail": "Google sign-in not configured"}, status_code=503)

    redirect_uri = resolve_redirect_uri(request, settings.google_redirect_uri, "google_callback")
    flow = _build_flow(settings, redirect_uri)
    restore_code_verifier(flow, request, _SESSION_PREFIX)
    id_token = token_exchange(flow, code)

    host = _sign_in_host(settings)
    factory = get_session_factory(request.app)
    with factory() as session:
        svc = IdentityService(auth=auth_adapter, users=SqlAlchemyUserRepository(session))
        try:
            sign_in_outcome = svc.sign_in(
                id_token, host=host, admin_emails=settings.admin_email_set
            )
        except BackOfficeAccessDenied:
            session.rollback()
            return JSONResponse({"detail": "Not authorised for the back office"}, status_code=403)
        session.commit()

    user = sign_in_outcome.user
    if sign_in_outcome.requested_pending:
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
        send_technician_access_requested(
            build_email_sender(settings),
            settings.admin_email_set,
            requester_name=user.name,
            requester_email=user.email,
        )
    elif sign_in_outcome.withdrew_pending:
        await _publish(
            request.app,
            ADMINS_CHANNEL,
            {"type": "technician_access.withdrawn", "user_id": str(user.id)},
        )

    clear_flow_session(request, _SESSION_PREFIX)
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
        "assist_disclaimer_accepted_at": (
            user.assist_disclaimer_accepted_at.isoformat()
            if user.assist_disclaimer_accepted_at
            else None
        ),
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

    factory = get_session_factory(request.app)
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

    factory = get_session_factory(request.app)
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


@router.post("/me/assist-disclaimer")
def accept_assist_disclaimer(
    request: Request,
    session_user: SessionUser = Depends(require_user),
):
    """Record that the caller accepted the assistant disclaimer.

    Idempotent: a caller who already accepted gets the same payload back with the original
    timestamp, so a reload or a second tab cannot restate when they agreed.
    """
    factory = get_session_factory(request.app)
    with factory() as session:
        repo = SqlAlchemyUserRepository(session)
        user = repo.get(session_user.id)
        user.accept_assist_disclaimer(datetime.now(timezone.utc))
        repo.save(user)
        session.commit()
    return JSONResponse(_me_payload(user))


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return JSONResponse({"status": "logged out"})
