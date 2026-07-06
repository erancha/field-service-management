"""Integration tests for the /calendar OAuth connect flow.

A Postgres 16 container is started once per module. Alembic migrations are
applied to it once. The injectable seams on app.state let the full
connect→persist→status path run against real PG without hitting real Google.

Auth is established via the existing /auth/google flow (token_exchange_override
+ auth_adapter_override), giving the TestClient a session cookie that the
calendar endpoints then consume. The connect endpoints require an APPROVED
TECHNICIAN, so tests that exercise them promote the signed-in user via
_claim_technician_role first.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlparse

import pytest
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from testcontainers.postgres import PostgresContainer

from fsm.google_calendar.adapters.repositories import SqlAlchemyCalendarConnectionRepository
from fsm.google_calendar.adapters.token_cipher import FernetTokenCipher
from fsm.identity.adapters.repositories import SqlAlchemyUserRepository
from fsm.identity.domain.role import Role
from fsm.identity.ports.auth import VerifiedIdentity
from fsm.platform.app import create_app
from fsm.platform.config import Settings


# ---------------------------------------------------------------------------
# Module-scoped container + migrated engine
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pg_session_factory():
    with PostgresContainer("postgres:16", driver="psycopg") as pg:
        url = pg.get_connection_url()
        os.environ["DATABASE_URL"] = url

        cfg = AlembicConfig()
        cfg.set_main_option(
            "script_location",
            str(__import__("pathlib").Path(__file__).parents[3] / "alembic"),
        )
        cfg.set_main_option("sqlalchemy.url", url)
        alembic_command.upgrade(cfg, "head")

        engine = create_engine(url)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        yield factory
        engine.dispose()
        del os.environ["DATABASE_URL"]


def _fernet_key() -> str:
    return Fernet.generate_key().decode()


def _settings_full(pg_url: str, token_key: str) -> Settings:
    return Settings(
        database_url=pg_url,
        app_env="test",
        google_client_id="test-client-id.apps.googleusercontent.com",
        google_client_secret="test-client-secret",
        google_redirect_uri="http://localhost:8001/auth/google/callback",
        session_secret="test-session-secret-32-bytes-long!!",
        fsm_token_key=token_key,
        google_calendar_redirect_uri="http://localhost:8001/calendar/connect/callback",
    )


def _settings_no_token_key(pg_url: str) -> Settings:
    return Settings(
        database_url=pg_url,
        app_env="test",
        google_client_id="test-client-id.apps.googleusercontent.com",
        google_client_secret="test-client-secret",
        google_redirect_uri="http://localhost:8001/auth/google/callback",
        session_secret="test-session-secret-32-bytes-long!!",
    )


def _fake_identity() -> VerifiedIdentity:
    return VerifiedIdentity(
        google_sub="google-sub-99999",
        email="tech@example.com",
        name="Tech Person",
    )


def _make_fake_auth_adapter(identity: VerifiedIdentity):
    adapter = MagicMock()
    adapter.verify.return_value = identity
    return adapter


def _make_fake_token_exchange(fake_id_token: str = "fake-id-token"):
    def exchange(flow, code: str) -> str:
        return fake_id_token
    return exchange


def _sign_in(client: TestClient, app) -> None:
    """Run the full /auth/google/login → callback flow to establish a session."""
    login_resp = client.get("/auth/google/login")
    assert login_resp.status_code == 307
    qs = parse_qs(urlparse(login_resp.headers["location"]).query)
    state = qs["state"][0]
    cb_resp = client.get(f"/auth/google/callback?code=fake-code&state={state}")
    assert cb_resp.status_code == 307


def _claim_technician_role(client: TestClient, pg_session_factory, approved: bool = True) -> uuid.UUID:
    """Move the signed-in user onto the TECHNICIAN role, approved or still pending.

    Sign-in in these tests arrives on a customer-host flow (fsm_role is unset), so the technician
    claim and the back-office approval decision are applied directly to the identity row.
    """
    user_id = uuid.UUID(client.get("/auth/me").json()["user_id"])
    with pg_session_factory() as session:
        repo = SqlAlchemyUserRepository(session)
        user = repo.get(user_id)
        user.request_role(Role.TECHNICIAN)
        if approved:
            user.approve(decided_by=uuid.uuid4(), at=datetime.now(timezone.utc))
        repo.save(user)
        session.commit()
    return user_id


class _FakeCalendarClient:
    """Minimal GoogleCalendarClient stub: only create_calendar is needed."""

    def __init__(self, calendar_id: str = "fsm-cal-123") -> None:
        self._calendar_id = calendar_id

    def create_calendar(self, summary: str) -> str:
        return self._calendar_id


class _ScopeDeniedCalendarClient:
    """Calendar client that fails on first use the way Google does when calendar scope is not granted.

    A technician can complete the OAuth redirect while granting only the sign-in scopes; the missing
    calendar grant only surfaces when the client first refreshes its access token to create the FSM
    calendar, raised from deep in google-auth as RefreshError('invalid_scope').
    """

    def create_calendar(self, summary: str) -> str:
        from google.auth.exceptions import RefreshError

        raise RefreshError(("invalid_scope: Bad Request", {"error": "invalid_scope"}))


# ---------------------------------------------------------------------------
# 1. /calendar/connect/login — unauthenticated → 401
# ---------------------------------------------------------------------------


def test_calendar_login_unauthenticated_returns_401(pg_session_factory):
    key = _fernet_key()
    settings = _settings_full(os.environ["DATABASE_URL"], key)
    app = create_app(session_factory=pg_session_factory, settings=settings)
    client = TestClient(app, follow_redirects=False)

    response = client.get("/calendar/connect/login")

    assert response.status_code == 401
    assert "authentication required" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 1b. Connect endpoints require an APPROVED TECHNICIAN (issue #14)
# ---------------------------------------------------------------------------


def test_calendar_connect_login_forbidden_for_customer(pg_session_factory):
    """A signed-in customer must not reach calendar onboarding.

    A connected calendar makes its owner bookable in customer-facing pooled availability, so the
    connect flow is gated on the approved-technician decision, not on authentication alone.
    """
    key = _fernet_key()
    settings = _settings_full(os.environ["DATABASE_URL"], key)
    app = create_app(session_factory=pg_session_factory, settings=settings)
    identity = VerifiedIdentity(
        google_sub="google-sub-customer-403",
        email="customer403@example.com",
        name="Plain Customer",
    )
    app.state.token_exchange_override = _make_fake_token_exchange()
    app.state.auth_adapter_override = _make_fake_auth_adapter(identity)
    client = TestClient(app, follow_redirects=False)

    _sign_in(client, app)

    response = client.get("/calendar/connect/login")

    assert response.status_code == 403


def test_calendar_connect_callback_forbidden_for_pending_technician(pg_session_factory):
    """A technician still awaiting approval cannot complete the connect callback.

    The role gate fires before any state validation or token exchange, and no connection is
    persisted for the pending technician.
    """
    key = _fernet_key()
    settings = _settings_full(os.environ["DATABASE_URL"], key)
    app = create_app(session_factory=pg_session_factory, settings=settings)
    identity = VerifiedIdentity(
        google_sub="google-sub-pending-403",
        email="pending403@example.com",
        name="Pending Tech",
    )
    app.state.token_exchange_override = _make_fake_token_exchange()
    app.state.auth_adapter_override = _make_fake_auth_adapter(identity)
    client = TestClient(app, follow_redirects=False)

    _sign_in(client, app)
    _claim_technician_role(client, pg_session_factory, approved=False)

    response = client.get("/calendar/connect/callback?code=x&state=anything")

    assert response.status_code == 403
    assert client.get("/calendar/status").json()["connected"] is False


# ---------------------------------------------------------------------------
# 2. /calendar/connect/login — authenticated but fsm_token_key unset → 503
# ---------------------------------------------------------------------------


def test_calendar_login_unconfigured_returns_503(pg_session_factory):
    settings = _settings_no_token_key(os.environ["DATABASE_URL"])
    app = create_app(session_factory=pg_session_factory, settings=settings)
    app.state.token_exchange_override = _make_fake_token_exchange()
    app.state.auth_adapter_override = _make_fake_auth_adapter(_fake_identity())
    client = TestClient(app, follow_redirects=False)

    _sign_in(client, app)
    _claim_technician_role(client, pg_session_factory)

    response = client.get("/calendar/connect/login")

    assert response.status_code == 503
    assert "not configured" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 3. /calendar/connect/login — authenticated + configured → 307 to accounts.google.com
# ---------------------------------------------------------------------------


def test_calendar_login_redirects_with_calendar_scope_and_state(pg_session_factory):
    key = _fernet_key()
    settings = _settings_full(os.environ["DATABASE_URL"], key)
    app = create_app(session_factory=pg_session_factory, settings=settings)
    app.state.token_exchange_override = _make_fake_token_exchange()
    app.state.auth_adapter_override = _make_fake_auth_adapter(_fake_identity())
    client = TestClient(app, follow_redirects=False)

    _sign_in(client, app)
    _claim_technician_role(client, pg_session_factory)

    response = client.get("/calendar/connect/login")

    assert response.status_code == 307
    location = response.headers["location"]
    assert "accounts.google.com" in location
    assert "calendar" in location
    assert "state=" in location


# ---------------------------------------------------------------------------
# 4. Full connect: login → callback → status + token decryption
# ---------------------------------------------------------------------------


def test_full_calendar_connect_flow(pg_session_factory):
    key = _fernet_key()
    settings = _settings_full(os.environ["DATABASE_URL"], key)
    app = create_app(session_factory=pg_session_factory, settings=settings)
    app.state.token_exchange_override = _make_fake_token_exchange()
    app.state.auth_adapter_override = _make_fake_auth_adapter(_fake_identity())
    client = TestClient(app, follow_redirects=False)

    # Authenticate as an approved technician
    _sign_in(client, app)
    _claim_technician_role(client, pg_session_factory)

    # Obtain calendar OAuth state via login endpoint
    login_resp = client.get("/calendar/connect/login")
    assert login_resp.status_code == 307
    qs = parse_qs(urlparse(login_resp.headers["location"]).query)
    cal_state = qs["state"][0]

    # Inject calendar-specific fakes
    app.state.calendar_token_exchange_override = lambda flow, code: "refresh-tok-xyz"
    fake_client = _FakeCalendarClient("fsm-cal-123")
    app.state.calendar_client_factory_override = lambda rt: fake_client

    # Callback with valid state
    cb_resp = client.get(f"/calendar/connect/callback?code=cal-code&state={cal_state}")
    assert cb_resp.status_code == 307
    assert cb_resp.headers["location"] == "/"

    # Status shows connected
    status_resp = client.get("/calendar/status")
    assert status_resp.status_code == 200
    data = status_resp.json()
    assert data["connected"] is True
    assert data["fsm_calendar_id"] == "fsm-cal-123"

    # Stored token decrypts to the original refresh token
    me_resp = client.get("/auth/me")
    technician_id = uuid.UUID(me_resp.json()["user_id"])
    with pg_session_factory() as session:
        repo = SqlAlchemyCalendarConnectionRepository(session)
        encrypted = repo.get_encrypted_token(technician_id)
    assert FernetTokenCipher(key).decrypt(encrypted) == "refresh-tok-xyz"


class _NoProvisionCalendarClient:
    """Reconnect-time client: create_calendar must never be called, so it fails loudly if it is.

    A reconnect reuses the calendar provisioned on the first connect. Any attempt to provision a
    second one would leak an orphan "Field Service Management" calendar on the technician's account.
    """

    def create_calendar(self, summary: str) -> str:
        raise AssertionError("reconnect must reuse the existing calendar, not provision a new one")


def test_calendar_reconnect_stores_fresh_token_and_reactivates(pg_session_factory):
    """A technician whose connection is DISCONNECTED reconnects successfully.

    The fresh refresh token replaces the stale one, status returns to CONNECTED, and the original
    calendar is reused (no second calendar provisioned). Reproduces the reconnect no-op where the
    duplicate insert was swallowed: the browser saw success while the stale token and DISCONNECTED
    row survived and every attempt leaked another calendar.
    """
    key = _fernet_key()
    settings = _settings_full(os.environ["DATABASE_URL"], key)
    app = create_app(session_factory=pg_session_factory, settings=settings)
    identity = VerifiedIdentity(
        google_sub="google-sub-reconnect",
        email="reconnect@example.com",
        name="Reconnect Tech",
    )
    app.state.token_exchange_override = _make_fake_token_exchange()
    app.state.auth_adapter_override = _make_fake_auth_adapter(identity)
    client = TestClient(app, follow_redirects=False)

    _sign_in(client, app)
    technician_id = _claim_technician_role(client, pg_session_factory)

    # First connect: provision calendar and store the initial token.
    cal_state = parse_qs(urlparse(client.get("/calendar/connect/login").headers["location"]).query)["state"][0]
    app.state.calendar_token_exchange_override = lambda flow, code: "stale-token"
    app.state.calendar_client_factory_override = lambda rt: _FakeCalendarClient("fsm-cal-reconnect")
    first = client.get(f"/calendar/connect/callback?code=c1&state={cal_state}")
    assert first.status_code == 307

    # Simulate a credential revocation leaving the row DISCONNECTED.
    with pg_session_factory() as session:
        repo = SqlAlchemyCalendarConnectionRepository(session)
        connection = repo.get(technician_id)
        connection.disconnect()
        repo.save(connection)
        session.commit()

    # Reconnect: a fresh consent yields a new token; no new calendar may be provisioned.
    cal_state2 = parse_qs(urlparse(client.get("/calendar/connect/login").headers["location"]).query)["state"][0]
    app.state.calendar_token_exchange_override = lambda flow, code: "fresh-token"
    app.state.calendar_client_factory_override = lambda rt: _NoProvisionCalendarClient()
    second = client.get(f"/calendar/connect/callback?code=c2&state={cal_state2}")
    assert second.status_code == 307

    status = client.get("/calendar/status").json()
    assert status["connected"] is True
    assert status["fsm_calendar_id"] == "fsm-cal-reconnect"

    with pg_session_factory() as session:
        encrypted = SqlAlchemyCalendarConnectionRepository(session).get_encrypted_token(technician_id)
    assert FernetTokenCipher(key).decrypt(encrypted) == "fresh-token"


# ---------------------------------------------------------------------------
# 5. Callback with bad state → 400
# ---------------------------------------------------------------------------


def test_calendar_callback_bad_state_returns_400(pg_session_factory):
    key = _fernet_key()
    settings = _settings_full(os.environ["DATABASE_URL"], key)
    app = create_app(session_factory=pg_session_factory, settings=settings)
    app.state.token_exchange_override = _make_fake_token_exchange()
    app.state.auth_adapter_override = _make_fake_auth_adapter(_fake_identity())
    client = TestClient(app, follow_redirects=False)

    _sign_in(client, app)
    _claim_technician_role(client, pg_session_factory)
    # Initiate login to set calendar_oauth_state in session
    client.get("/calendar/connect/login")

    response = client.get("/calendar/connect/callback?code=x&state=wrong-state-value")

    assert response.status_code == 400
    assert "state" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 5b. Callback flow carries the PKCE code_verifier minted at login
# ---------------------------------------------------------------------------


def test_calendar_callback_propagates_pkce_code_verifier_to_token_exchange(pg_session_factory):
    """The flow handed to the token exchange must carry the code_verifier minted at login.

    authorization_url() sends Google a PKCE code_challenge, so the token exchange must present the
    matching code_verifier. Login and callback build independent Flow objects, so the verifier has
    to ride the session across the redirect — without it Google rejects the exchange with
    invalid_grant "Missing code verifier".
    """
    key = _fernet_key()
    settings = _settings_full(os.environ["DATABASE_URL"], key)
    app = create_app(session_factory=pg_session_factory, settings=settings)
    app.state.token_exchange_override = _make_fake_token_exchange()
    app.state.auth_adapter_override = _make_fake_auth_adapter(_fake_identity())
    client = TestClient(app, follow_redirects=False)

    _sign_in(client, app)
    _claim_technician_role(client, pg_session_factory)

    seen = {}

    def capturing_exchange(flow, code: str) -> str:
        seen["code_verifier"] = flow.code_verifier
        return "refresh-tok-pkce"

    app.state.calendar_token_exchange_override = capturing_exchange
    app.state.calendar_client_factory_override = lambda rt: _FakeCalendarClient("fsm-cal-pkce")

    login_resp = client.get("/calendar/connect/login")
    location = login_resp.headers["location"]
    assert "code_challenge=" in location  # PKCE is active on the login redirect
    state = parse_qs(urlparse(location).query)["state"][0]

    cb_resp = client.get(f"/calendar/connect/callback?code=cal-code&state={state}")

    assert cb_resp.status_code == 307
    assert seen["code_verifier"], (
        "calendar callback flow reached token exchange without a PKCE code_verifier"
    )


# ---------------------------------------------------------------------------
# 5c. Calendar flow requests only the narrow app-created + freebusy scopes
# ---------------------------------------------------------------------------


def test_calendar_flow_requests_only_app_created_and_freebusy_scopes():
    """OAuth consent must request only calendar.app.created + calendar.freebusy.

    The privacy-by-construction model (design D2/D3) depends on the app never being granted access
    to the technician's other calendars: app.created confines it to calendars the app itself created,
    and freebusy returns only opaque busy/free blocks. The broad .../auth/calendar scope would grant
    read/write to every calendar in the account and must never be requested.
    """
    from fsm.platform.api.calendar_routes import _build_flow

    settings = _settings_full("postgresql+psycopg://unused:unused@localhost/unused", _fernet_key())
    flow = _build_flow(settings, settings.google_calendar_redirect_uri)
    auth_url, _ = flow.authorization_url()
    scopes = set(parse_qs(urlparse(auth_url).query)["scope"][0].split())

    assert scopes == {
        "https://www.googleapis.com/auth/calendar.app.created",
        "https://www.googleapis.com/auth/calendar.freebusy",
    }
    assert "https://www.googleapis.com/auth/calendar" not in scopes


# ---------------------------------------------------------------------------
# 5d. Calendar code exchange relaxes scope validation independently of sign-in
# ---------------------------------------------------------------------------


def test_calendar_token_exchange_tolerates_scope_mismatch(monkeypatch):
    """The calendar exchange must not 500 when the granted scope set differs from requested.

    With include_granted_scopes=true, Google folds the already-granted sign-in scopes
    (openid/email/profile) into the calendar grant, so the granted set never byte-matches the
    requested calendar scopes. oauthlib treats any mismatch as fatal unless OAUTHLIB_RELAX_TOKEN_SCOPE
    is set. That relaxation must be self-contained in the calendar exchange, not inherited from a
    sign-in exchange that happened to run first in the same process (a session restored from the
    signed cookie, or sign-in handled by another per-role process, leaves the flag unset).
    """
    import json

    import requests
    from requests_oauthlib import OAuth2Session

    from fsm.platform.api.calendar_routes import _build_flow, _real_token_exchange

    settings = _settings_full("postgresql+psycopg://unused:unused@localhost/unused", _fernet_key())
    token_body = json.dumps(
        {
            "access_token": "fake-access-token",
            "refresh_token": "the-refresh-token",
            "token_type": "Bearer",
            "expires_in": 3599,
            "scope": "openid https://www.googleapis.com/auth/calendar.app.created "
            "https://www.googleapis.com/auth/calendar.freebusy "
            "https://www.googleapis.com/auth/userinfo.email",
        }
    )

    def fake_request(self, method, url, **kwargs):
        resp = requests.models.Response()
        resp.status_code = 200
        resp._content = token_body.encode()
        resp.headers["Content-Type"] = "application/json"
        resp.url = url
        prepared = requests.PreparedRequest()
        prepared.url = url
        resp.request = prepared
        return resp

    monkeypatch.setattr(OAuth2Session, "request", fake_request)
    monkeypatch.delenv("OAUTHLIB_RELAX_TOKEN_SCOPE", raising=False)

    flow = _build_flow(settings, settings.google_calendar_redirect_uri)
    assert _real_token_exchange(flow, "fake-code") == "the-refresh-token"


# ---------------------------------------------------------------------------
# 5e. Callback redirects to the app with a rejection flag (never a 500) when the
#     calendar scope was not granted, or the technician declined/cancelled
# ---------------------------------------------------------------------------


def _denied_flag(location: str) -> str | None:
    return parse_qs(urlparse(location).query).get("calendar_connect", [None])[0]


def test_calendar_callback_redirects_with_rejection_when_calendar_scope_not_granted(pg_session_factory):
    """A missing calendar grant sends the technician back to the app flagged, not a 500 or raw JSON.

    When Google returns only the sign-in scopes, the first Calendar API call fails as the client
    refreshes its token. The callback logs the cause and 307-redirects to /?calendar_connect=denied so
    the SPA renders a friendly banner, and persists no connection.
    """
    key = _fernet_key()
    settings = _settings_full(os.environ["DATABASE_URL"], key)
    app = create_app(session_factory=pg_session_factory, settings=settings)
    identity = VerifiedIdentity(
        google_sub="google-sub-scope-denied",
        email="scopedenied@example.com",
        name="Scope Denied",
    )
    app.state.token_exchange_override = _make_fake_token_exchange()
    app.state.auth_adapter_override = _make_fake_auth_adapter(identity)
    client = TestClient(app, follow_redirects=False, raise_server_exceptions=False)

    _sign_in(client, app)
    _claim_technician_role(client, pg_session_factory)
    login_resp = client.get("/calendar/connect/login")
    cal_state = parse_qs(urlparse(login_resp.headers["location"]).query)["state"][0]

    app.state.calendar_token_exchange_override = lambda flow, code: "refresh-tok-noscope"
    app.state.calendar_client_factory_override = lambda rt: _ScopeDeniedCalendarClient()

    resp = client.get(f"/calendar/connect/callback?code=cal-code&state={cal_state}")

    assert resp.status_code == 307
    assert _denied_flag(resp.headers["location"]) == "denied"

    status = client.get("/calendar/status").json()
    assert status["connected"] is False


def test_calendar_callback_redirects_with_rejection_when_technician_declines(pg_session_factory):
    """A cancelled/declined consent (Google returns ?error=access_denied, no code) is not a crash.

    The callback detects the OAuth error parameter up front — before any token exchange — logs it, and
    307-redirects to the app with the same rejection flag, persisting no connection.
    """
    key = _fernet_key()
    settings = _settings_full(os.environ["DATABASE_URL"], key)
    app = create_app(session_factory=pg_session_factory, settings=settings)
    identity = VerifiedIdentity(
        google_sub="google-sub-declined",
        email="declined@example.com",
        name="Declined",
    )
    app.state.token_exchange_override = _make_fake_token_exchange()
    app.state.auth_adapter_override = _make_fake_auth_adapter(identity)
    client = TestClient(app, follow_redirects=False, raise_server_exceptions=False)

    _sign_in(client, app)
    _claim_technician_role(client, pg_session_factory)
    login_resp = client.get("/calendar/connect/login")
    cal_state = parse_qs(urlparse(login_resp.headers["location"]).query)["state"][0]

    # Fully faked success path so this test stays hermetic; the OAuth error must short-circuit before
    # it is ever reached.
    app.state.calendar_token_exchange_override = lambda flow, code: "refresh-tok-decline"
    app.state.calendar_client_factory_override = lambda rt: _FakeCalendarClient("fsm-cal-decline")

    resp = client.get(f"/calendar/connect/callback?error=access_denied&state={cal_state}")

    assert resp.status_code == 307
    assert _denied_flag(resp.headers["location"]) == "denied"

    status = client.get("/calendar/status").json()
    assert status["connected"] is False


# ---------------------------------------------------------------------------
# 6. /calendar/status — no connection → connected: false
# ---------------------------------------------------------------------------


def test_calendar_status_no_connection_returns_disconnected(pg_session_factory):
    key = _fernet_key()
    settings = _settings_full(os.environ["DATABASE_URL"], key)
    app = create_app(session_factory=pg_session_factory, settings=settings)
    # Use a unique identity so there is no prior connection for this user
    identity = VerifiedIdentity(
        google_sub="google-sub-new-unique",
        email="newtech@example.com",
        name="New Tech",
    )
    app.state.token_exchange_override = _make_fake_token_exchange()
    app.state.auth_adapter_override = _make_fake_auth_adapter(identity)
    client = TestClient(app, follow_redirects=False)

    _sign_in(client, app)

    response = client.get("/calendar/status")

    assert response.status_code == 200
    data = response.json()
    assert data["connected"] is False
    assert data["fsm_calendar_id"] is None
