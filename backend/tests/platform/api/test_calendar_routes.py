"""Integration tests for the /calendar OAuth connect flow.

A Postgres 16 container is started once per module. Alembic migrations are
applied to it once. The injectable seams on app.state let the full
connect→persist→status path run against real PG without hitting real Google.

Auth is established via the existing /auth/google flow (token_exchange_override
+ auth_adapter_override), giving the TestClient a session cookie that the
calendar endpoints then consume.
"""
from __future__ import annotations

import os
import uuid
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

from fsm.calendar.adapters.repositories import SqlAlchemyCalendarConnectionRepository
from fsm.calendar.adapters.token_cipher import FernetTokenCipher
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


class _FakeCalendarClient:
    """Minimal GoogleCalendarClient stub: only create_calendar is needed."""

    def __init__(self, calendar_id: str = "fsm-cal-123") -> None:
        self._calendar_id = calendar_id

    def create_calendar(self, summary: str) -> str:
        return self._calendar_id


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
    assert "not authenticated" in response.json()["detail"].lower()


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

    # Authenticate
    _sign_in(client, app)

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
