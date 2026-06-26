"""FastAPI router for technician Google Calendar OAuth connect flow.

Wiring:
- GET /calendar/connect/login    → redirect to Google Calendar authorization (or 401/503)
- GET /calendar/connect/callback → exchange code, provision FSM calendar, persist connection
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

import secrets
from typing import Callable
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from fsm.calendar.adapters.repositories import SqlAlchemyCalendarConnectionRepository
from fsm.calendar.adapters.token_cipher import FernetTokenCipher
from fsm.calendar.application.connection_service import CalendarConnectionService
from fsm.calendar.domain.errors import DuplicateTechnicianError, NotFoundError

router = APIRouter(prefix="/calendar")

_CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar"


def _build_flow(settings):
    """Construct a google_auth_oauthlib Flow configured for calendar scope."""
    from google_auth_oauthlib.flow import Flow

    client_config = {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret.get_secret_value(),
            "redirect_uris": [settings.google_calendar_redirect_uri],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    return Flow.from_client_config(
        client_config,
        scopes=[_CALENDAR_SCOPE],
        redirect_uri=settings.google_calendar_redirect_uri,
    )


def _real_token_exchange(flow, code: str) -> str:
    """Exchange the authorization code for a refresh token via the real Google endpoint."""
    flow.fetch_token(code=code)
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

    flow = _build_flow(settings)
    state = secrets.token_urlsafe(32)
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        state=state,
        include_granted_scopes="true",
    )
    request.session["calendar_oauth_state"] = state
    return RedirectResponse(auth_url, status_code=307)


@router.get("/connect/callback")
def calendar_connect_callback(request: Request, code: str = "", state: str = ""):
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

    token_exchange = _get_token_exchange(request.app)
    client_factory = _get_client_factory(request.app, settings)

    flow = _build_flow(settings)
    refresh_token = token_exchange(flow, code)
    client = client_factory(refresh_token)

    technician_id = UUID(request.session["user_id"])
    factory = _get_session_factory(request.app)
    with factory() as session:
        service = CalendarConnectionService(
            repo=SqlAlchemyCalendarConnectionRepository(session),
            cipher=FernetTokenCipher(settings.fsm_token_key.get_secret_value()),
            client=client,
        )
        try:
            service.connect(technician_id, refresh_token)
            session.commit()
        except DuplicateTechnicianError:
            session.rollback()

    request.session.pop("calendar_oauth_state", None)
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
