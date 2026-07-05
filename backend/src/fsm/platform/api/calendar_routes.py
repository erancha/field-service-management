"""FastAPI router for technician Google Calendar OAuth connect flow.

Wiring:
- GET /calendar/connect/login    → redirect to Google Calendar authorization (or 401/503)
- GET /calendar/connect/callback → exchange code, connect or reconnect the technician's calendar,
                                   persist connection; denied or insufficient consent redirects
                                   back to the SPA flagged
- GET /calendar/status           → return connected status for the session user

Authentication is gated purely on an authenticated session (user_id present). The
deployment environment (FSM_ROLE) determines whether the "Connect Google Calendar"
button is surfaced; this router does not enforce roles. A customer-role deployment
simply never links to these endpoints.

Injectable seams on app.state allow tests to bypass real Google without patching globals:
  app.state.calendar_token_exchange_override  — callable(flow, code) → refresh_token str
  app.state.calendar_client_factory_override  — callable(refresh_token) → GoogleCalendarClient
"""
from __future__ import annotations

import logging
import secrets
from typing import Callable
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from fsm.calendar.adapters.repositories import SqlAlchemyCalendarConnectionRepository
from fsm.calendar.adapters.token_cipher import FernetTokenCipher
from fsm.calendar.application.connection_service import CalendarConnectionService
from fsm.calendar.domain.errors import NotFoundError
from fsm.calendar.scopes import CALENDAR_OAUTH_SCOPES
from fsm.platform.api.oauth_redirect import resolve_redirect_uri
from fsm.platform.api.oauth_token import fetch_token_relaxed

router = APIRouter(prefix="/calendar")

_log = logging.getLogger(__name__)

# Operator runbook holding the exact Google Cloud Console steps; referenced from the failure log
# so the volatile click-path lives in one updatable place, not in code.
_SETUP_RUNBOOK = "docs/calendar-setup.md"


def _google_connect_errors() -> tuple[type[BaseException], ...]:
    """Google client failures that mean the calendar connection could not be established.

    A refused or insufficient consent — the technician did not grant the app-created / free-busy
    scopes — reaches the callback as a RefreshError when the client first refreshes its access token,
    or as an HttpError if the API itself rejects the call. Both resolve to a controlled rejection
    redirect back to the app.
    """
    from google.auth.exceptions import GoogleAuthError
    from googleapiclient.errors import HttpError

    return (GoogleAuthError, HttpError)


def _reject_calendar_connect(request: Request) -> RedirectResponse:
    """Send the browser back to the SPA flagged so it renders a friendly banner with a retry.

    Clears the one-shot OAuth state from the session — a retry via /calendar/connect/login mints
    fresh state. The technician-facing wording lives in the SPA; the operator-facing cause is logged
    by the caller.
    """
    request.session.pop("calendar_oauth_state", None)
    request.session.pop("calendar_code_verifier", None)
    return RedirectResponse("/?calendar_connect=denied", status_code=307)


def _build_flow(settings, redirect_uri: str):
    """Construct a google_auth_oauthlib Flow configured for the narrow calendar scopes."""
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
    return Flow.from_client_config(
        client_config,
        scopes=list(CALENDAR_OAUTH_SCOPES),
        redirect_uri=redirect_uri,
    )


def _real_token_exchange(flow, code: str) -> str:
    """Exchange the authorization code for a refresh token via the real Google endpoint."""
    fetch_token_relaxed(flow, code)
    return flow.credentials.refresh_token  # type: ignore[attr-defined]


def _get_token_exchange(app) -> Callable:
    override = getattr(app.state, "calendar_token_exchange_override", None)
    return override if override is not None else _real_token_exchange


def _get_client_factory(app, settings) -> Callable:
    override = getattr(app.state, "calendar_client_factory_override", None)
    if override is not None:
        return override

    from fsm.calendar.adapters.client_factory import build_calendar_client

    def _default_factory(refresh_token: str):
        return build_calendar_client(
            refresh_token=refresh_token,
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret.get_secret_value(),
        )

    return _default_factory


def _get_session_factory(app):
    from fsm.platform.app import _get_session_factory as _lazy

    return _lazy(app)


def _get_settings(request: Request):
    return getattr(request.app.state, "settings", None) or __import__(
        "fsm.platform.config", fromlist=["get_settings"]
    ).get_settings()


def _is_calendar_configured(settings) -> bool:
    return bool(
        settings.google_client_id
        and settings.google_client_secret
        and settings.fsm_token_key
    )


@router.get("/connect/login")
def calendar_connect_login(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)

    settings = _get_settings(request)
    if not _is_calendar_configured(settings):
        return JSONResponse(
            {"detail": "Calendar integration not configured"}, status_code=503
        )

    redirect_uri = resolve_redirect_uri(
        request, settings.google_calendar_redirect_uri, "calendar_connect_callback"
    )
    flow = _build_flow(settings, redirect_uri)
    state = secrets.token_urlsafe(32)
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        state=state,
        include_granted_scopes="true",
    )
    request.session["calendar_oauth_state"] = state
    # authorization_url() mints a PKCE code_verifier and sends its derived challenge to Google. The
    # callback builds a separate Flow, so the verifier must ride the session to complete the exchange.
    request.session["calendar_code_verifier"] = flow.code_verifier
    return RedirectResponse(auth_url, status_code=307)


@router.get("/connect/callback")
def calendar_connect_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    expected_state = request.session.get("calendar_oauth_state")
    if not expected_state or not secrets.compare_digest(expected_state, state):
        return JSONResponse(
            {"detail": "Invalid or missing state parameter"}, status_code=400
        )

    settings = _get_settings(request)
    if not _is_calendar_configured(settings):
        return JSONResponse(
            {"detail": "Calendar integration not configured"}, status_code=503
        )

    # The technician declined or cancelled on Google's consent screen: Google redirects back with an
    # ?error (e.g. access_denied) and no code. Reject cleanly rather than exchanging an empty code.
    if error:
        _log.warning(
            "Calendar connect declined by technician %s: %s",
            request.session.get("user_id"),
            error,
        )
        return _reject_calendar_connect(request)

    token_exchange = _get_token_exchange(request.app)
    client_factory = _get_client_factory(request.app, settings)

    redirect_uri = resolve_redirect_uri(
        request, settings.google_calendar_redirect_uri, "calendar_connect_callback"
    )
    flow = _build_flow(settings, redirect_uri)
    flow.code_verifier = request.session.get("calendar_code_verifier")

    technician_id = UUID(request.session["user_id"])
    factory = _get_session_factory(request.app)
    try:
        refresh_token = token_exchange(flow, code)
        client = client_factory(refresh_token)
        with factory() as session:
            service = CalendarConnectionService(
                repo=SqlAlchemyCalendarConnectionRepository(session),
                cipher=FernetTokenCipher(settings.fsm_token_key.get_secret_value()),
                client=client,
            )
            service.connect(technician_id, refresh_token)
            session.commit()
    except _google_connect_errors() as exc:
        # A denied or insufficient calendar consent only fails here, on the first Google call
        # (create_calendar refreshing the access token). The operator-facing cause and remediation
        # runbook go to the log; the browser is sent back to the app flagged.
        _log.warning(
            "Calendar connect failed for technician %s — Google rejected the credentials; the "
            "required calendar scopes (%s) were likely not granted. See %s. Raw error: %s",
            technician_id,
            ", ".join(CALENDAR_OAUTH_SCOPES),
            _SETUP_RUNBOOK,
            exc,
        )
        return _reject_calendar_connect(request)

    request.session.pop("calendar_oauth_state", None)
    request.session.pop("calendar_code_verifier", None)
    return RedirectResponse("/", status_code=307)


@router.get("/status")
def calendar_status(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)

    factory = _get_session_factory(request.app)
    with factory() as session:
        repo = SqlAlchemyCalendarConnectionRepository(session)
        try:
            connection = repo.get(UUID(user_id))
        except NotFoundError:
            return JSONResponse({"connected": False, "fsm_calendar_id": None})

    from fsm.calendar.domain.connection import CalendarConnectionStatus

    return JSONResponse(
        {
            "connected": connection.status == CalendarConnectionStatus.CONNECTED,
            "fsm_calendar_id": connection.fsm_calendar_id,
        }
    )
