"""FastAPI router for technician Google Calendar OAuth connect flow.

Wiring:
- GET /calendar/connect/login    → redirect to Google Calendar authorization (or 401/403/503)
- GET /calendar/connect/callback → exchange code, connect or reconnect the technician's calendar,
                                   persist connection, and re-project upcoming appointments when a
                                   deleted calendar was replaced; denied or insufficient consent
                                   redirects back to the SPA flagged
- POST /calendar/disconnect      → mark the caller's connection DISCONNECTED
- GET /calendar/status           → return connected status for the session user

The connect and disconnect endpoints require an APPROVED TECHNICIAN session: a connected calendar
makes its owner appear in customer-facing pooled availability, so calendar onboarding is gated on
the back-office approval decision, not on authentication alone. /calendar/status only reports the
caller's own connection and needs just an authenticated session.

Injectable seams on app.state allow tests to bypass real Google without patching globals:
  app.state.calendar_token_exchange_override  — callable(flow, code) → refresh_token str
  app.state.calendar_client_factory_override  — callable(refresh_token) → GoogleCalendarClient
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse

from fsm.google_calendar.adapters.repositories import SqlAlchemyCalendarConnectionRepository
from fsm.google_calendar.adapters.token_cipher import FernetTokenCipher
from fsm.google_calendar.application.connection_service import CalendarConnectionService
from fsm.google_calendar.domain.errors import NotFoundError
from fsm.google_calendar.scopes import CALENDAR_OAUTH_SCOPES
from fsm.platform.calendar_reprojection import reproject_active_appointments
from fsm.identity.domain.role import Role
from fsm.platform.api.auth_deps import SessionUser, require_role
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
from fsm.platform.api.oauth_redirect import resolve_redirect_uri

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


# Namespaces this flow's oauth session keys away from the sign-in flow's.
_SESSION_PREFIX = "calendar_"

# The exchanged credential is the refresh token, persisted (encrypted) for background sync.
_real_token_exchange = make_token_exchange("refresh_token")


def _reject_calendar_connect(request: Request) -> RedirectResponse:
    """Send the browser back to the SPA flagged so it renders a friendly banner with a retry.

    Clears the one-shot OAuth state from the session — a retry via /calendar/connect/login mints
    fresh state. The technician-facing wording lives in the SPA; the operator-facing cause is logged
    by the caller.
    """
    clear_flow_session(request, _SESSION_PREFIX)
    return RedirectResponse("/?calendar_connect=denied", status_code=307)


def _build_flow(settings, redirect_uri: str):
    """Construct the connect Flow, requesting only the narrow calendar scopes."""
    return build_flow(settings, redirect_uri, scopes=CALENDAR_OAUTH_SCOPES)


def _get_client_factory(app, settings) -> Callable:
    override = getattr(app.state, "calendar_client_factory_override", None)
    if override is not None:
        return override

    from fsm.google_calendar.adapters.client_factory import build_calendar_client

    def _default_factory(refresh_token: str):
        return build_calendar_client(
            refresh_token=refresh_token,
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret.get_secret_value(),
        )

    return _default_factory


def _is_calendar_configured(settings) -> bool:
    return bool(
        settings.google_client_id
        and settings.google_client_secret
        and settings.fsm_token_key
    )


@router.get("/connect/login")
def calendar_connect_login(
    request: Request, user: SessionUser = Depends(require_role(Role.TECHNICIAN))
):
    settings = get_settings(request)
    if not _is_calendar_configured(settings):
        return JSONResponse(
            {"detail": "Calendar integration not configured"}, status_code=503
        )

    redirect_uri = resolve_redirect_uri(
        request, settings.google_calendar_redirect_uri, "calendar_connect_callback"
    )
    flow = _build_flow(settings, redirect_uri)
    return begin_authorization(request, flow, _SESSION_PREFIX, prompt="consent")


@router.get("/connect/callback")
def calendar_connect_callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    user: SessionUser = Depends(require_role(Role.TECHNICIAN)),
):
    if not state_matches(request, state, _SESSION_PREFIX):
        return JSONResponse(
            {"detail": "Invalid or missing state parameter"}, status_code=400
        )

    settings = get_settings(request)
    if not _is_calendar_configured(settings):
        return JSONResponse(
            {"detail": "Calendar integration not configured"}, status_code=503
        )

    # The technician declined or cancelled on Google's consent screen: Google redirects back with an
    # ?error (e.g. access_denied) and no code. Reject cleanly rather than exchanging an empty code.
    if error:
        _log.warning("Calendar connect declined by technician %s: %s", user.id, error)
        return _reject_calendar_connect(request)

    token_exchange = resolve_token_exchange(
        request.app, "calendar_token_exchange_override", _real_token_exchange
    )
    client_factory = _get_client_factory(request.app, settings)

    redirect_uri = resolve_redirect_uri(
        request, settings.google_calendar_redirect_uri, "calendar_connect_callback"
    )
    flow = _build_flow(settings, redirect_uri)
    restore_code_verifier(flow, request, _SESSION_PREFIX)

    technician_id = user.id
    factory = get_session_factory(request.app)
    try:
        refresh_token = token_exchange(flow, code)
        client = client_factory(refresh_token)
        with factory() as session:
            repo = SqlAlchemyCalendarConnectionRepository(session)
            try:
                previous_calendar_id = repo.get(technician_id).fsm_calendar_id
            except NotFoundError:
                previous_calendar_id = None
            service = CalendarConnectionService(
                repo=repo,
                cipher=FernetTokenCipher(settings.fsm_token_key.get_secret_value()),
                client=client,
            )
            connection = service.connect(technician_id, refresh_token)
            # A changed calendar id means the previous one was deleted in Google and a replacement
            # was provisioned; its events must be rebuilt from the appointments held here.
            if (
                previous_calendar_id is not None
                and connection.fsm_calendar_id != previous_calendar_id
            ):
                reproject_active_appointments(
                    session, technician_id, now=datetime.now(timezone.utc)
                )
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

    clear_flow_session(request, _SESSION_PREFIX)
    return RedirectResponse("/", status_code=307)


@router.post("/disconnect")
def calendar_disconnect(
    request: Request, user: SessionUser = Depends(require_role(Role.TECHNICIAN))
):
    """Mark the caller's calendar connection DISCONNECTED, dropping them from pooled availability.

    Gated on the same approved-technician role as connect. Reports 404 when the caller has no
    connection, so the absence surfaces instead of passing as a no-op success.
    """
    factory = get_session_factory(request.app)
    with factory() as session:
        repo = SqlAlchemyCalendarConnectionRepository(session)
        try:
            connection = repo.get(user.id)
        except NotFoundError:
            return JSONResponse(
                {"detail": "No calendar connection to disconnect"}, status_code=404
            )
        connection.disconnect()
        repo.save(connection)
        session.commit()

    return JSONResponse({"connected": False})


@router.get("/status")
def calendar_status(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)

    factory = get_session_factory(request.app)
    with factory() as session:
        repo = SqlAlchemyCalendarConnectionRepository(session)
        try:
            connection = repo.get(UUID(user_id))
        except NotFoundError:
            return JSONResponse({"connected": False, "fsm_calendar_id": None})

    from fsm.google_calendar.domain.connection import CalendarConnectionStatus

    return JSONResponse(
        {
            "connected": connection.status == CalendarConnectionStatus.CONNECTED,
            "fsm_calendar_id": connection.fsm_calendar_id,
        }
    )
