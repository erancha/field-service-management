"""Integration tests for Google OAuth / session auth endpoints.

A Postgres 16 container is started once per module. Alembic migrations are
applied to it once. The injectable seams (token_exchange_override and
auth_adapter_override on app.state) let the full callback→user→session path
run against real PG without hitting real Google.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from testcontainers.postgres import PostgresContainer

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


def _settings_with_google(pg_url: str, **overrides) -> Settings:
    return Settings(
        database_url=pg_url,
        app_env="test",
        google_client_id="test-client-id.apps.googleusercontent.com",
        google_client_secret="test-client-secret",
        google_redirect_uri="http://localhost:8001/auth/google/callback",
        session_secret="test-session-secret-32-bytes-long!!",
        **overrides,
    )


def _settings_without_google(pg_url: str) -> Settings:
    return Settings(
        database_url=pg_url,
        app_env="test",
        session_secret="test-session-secret-32-bytes-long!!",
    )


def _fake_identity() -> VerifiedIdentity:
    return VerifiedIdentity(
        google_sub="google-sub-12345",
        email="alice@example.com",
        name="Alice Example",
    )


def _make_fake_auth_adapter(identity: VerifiedIdentity):
    """Return an AuthPort stub that always returns the given identity."""
    adapter = MagicMock()
    adapter.verify.return_value = identity
    return adapter


def _make_fake_token_exchange(fake_id_token: str = "fake-id-token"):
    """Return a token-exchange callable that returns a canned id_token string."""
    def exchange(flow, code: str) -> str:
        return fake_id_token
    return exchange


# ---------------------------------------------------------------------------
# 1. /auth/google/login — Google configured → 307 to accounts.google.com
# ---------------------------------------------------------------------------


def test_google_login_redirects_to_google(pg_session_factory):
    settings = _settings_with_google(os.environ["DATABASE_URL"])
    app = create_app(session_factory=pg_session_factory, settings=settings)
    client = TestClient(app, follow_redirects=False)

    response = client.get("/auth/google/login")

    assert response.status_code == 307
    location = response.headers["location"]
    assert "accounts.google.com" in location
    assert "test-client-id.apps.googleusercontent.com" in location
    assert "openid" in location
    assert "email" in location
    assert "profile" in location
    # state is present
    assert "state=" in location


# ---------------------------------------------------------------------------
# 2. /auth/google/login — Google NOT configured → 503
# ---------------------------------------------------------------------------


def test_google_login_returns_503_when_not_configured(pg_session_factory):
    settings = _settings_without_google(os.environ["DATABASE_URL"])
    app = create_app(session_factory=pg_session_factory, settings=settings)
    client = TestClient(app, follow_redirects=False)

    response = client.get("/auth/google/login")

    assert response.status_code == 503
    assert "not configured" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 2b. Redirect URI: derived per-host when unset, configured value as override
# ---------------------------------------------------------------------------


def _redirect_uri_from_login(client) -> str:
    from urllib.parse import parse_qs, urlparse

    location = client.get("/auth/google/login").headers["location"]
    return parse_qs(urlparse(location).query)["redirect_uri"][0]


def test_google_login_derives_redirect_uri_from_request_host_when_unset(pg_session_factory):
    """With no configured redirect URI, login derives the callback from the request's own host.

    Each role sits on its own edge host behind nginx, so the callback must return there; deriving it
    per request lets one OAuth client serve every role without a hard-coded host.
    """
    settings = Settings(
        database_url=os.environ["DATABASE_URL"],
        app_env="test",
        google_client_id="test-client-id.apps.googleusercontent.com",
        google_client_secret="test-client-secret",
        google_redirect_uri="",
        session_secret="test-session-secret-32-bytes-long!!",
    )
    app = create_app(session_factory=pg_session_factory, settings=settings)
    client = TestClient(app, follow_redirects=False)

    assert _redirect_uri_from_login(client) == "http://testserver/auth/google/callback"


def test_google_login_uses_configured_redirect_uri_override(pg_session_factory):
    """An explicit redirect URI overrides per-host derivation, for a fixed public deployment."""
    settings = _settings_with_google(os.environ["DATABASE_URL"])
    app = create_app(session_factory=pg_session_factory, settings=settings)
    client = TestClient(app, follow_redirects=False)

    assert _redirect_uri_from_login(client) == "http://localhost:8001/auth/google/callback"


# ---------------------------------------------------------------------------
# 3. Full callback → user → session flow with injected fakes
# ---------------------------------------------------------------------------


def test_callback_creates_user_sets_session_and_me_returns_user(pg_session_factory):
    settings = _settings_with_google(os.environ["DATABASE_URL"])
    identity = _fake_identity()
    app = create_app(session_factory=pg_session_factory, settings=settings)
    app.state.token_exchange_override = _make_fake_token_exchange("fake-id-token")
    app.state.auth_adapter_override = _make_fake_auth_adapter(identity)

    client = TestClient(app, follow_redirects=False)

    # Obtain a valid state by calling /auth/google/login first
    login_resp = client.get("/auth/google/login")
    assert login_resp.status_code == 307
    location = login_resp.headers["location"]
    # Extract state from the redirect URL
    from urllib.parse import parse_qs, urlparse
    qs = parse_qs(urlparse(location).query)
    state = qs["state"][0]

    # Call callback with the real state from the session
    callback_resp = client.get(f"/auth/google/callback?code=fake-code&state={state}")
    assert callback_resp.status_code == 307
    assert callback_resp.headers["location"] == "/"

    # /auth/me should return the signed-in user
    me_resp = client.get("/auth/me")
    assert me_resp.status_code == 200
    data = me_resp.json()
    assert data["email"] == "alice@example.com"
    assert data["role"] == "CUSTOMER"
    assert "user_id" in data

    # /auth/logout clears the session
    logout_resp = client.post("/auth/logout")
    assert logout_resp.status_code == 200

    # /auth/me returns 401 after logout
    me_after_logout = client.get("/auth/me")
    assert me_after_logout.status_code == 401


# ---------------------------------------------------------------------------
# 3a. Sign-in landing in TECHNICIAN/PENDING emails the back-office admins
# ---------------------------------------------------------------------------


def test_pending_technician_sign_in_emails_back_office_admins(pg_session_factory, caplog):
    """A sign-in that lands in TECHNICIAN/PENDING emails every configured admin.

    The SSE push reaches only admins with the dashboard open; the email must go out from the same
    callback so approval latency never depends on an open browser tab. The suite runs with SMTP
    disabled, so delivery is observed through the LoggingEmailSender fallback's log record.
    """
    import logging

    settings = _settings_with_google(
        os.environ["DATABASE_URL"],
        fsm_role="technician",
        admin_emails="admin@example.com",
    )
    identity = VerifiedIdentity(
        google_sub="google-sub-tech-pending",
        email="tech.pending@example.com",
        name="Tex Pending",
    )
    app = create_app(session_factory=pg_session_factory, settings=settings)
    app.state.token_exchange_override = _make_fake_token_exchange()
    app.state.auth_adapter_override = _make_fake_auth_adapter(identity)
    client = TestClient(app, follow_redirects=False)

    from urllib.parse import parse_qs, urlparse

    login_resp = client.get("/auth/google/login")
    state = parse_qs(urlparse(login_resp.headers["location"]).query)["state"][0]

    with caplog.at_level(logging.INFO, logger="fsm.notifications.adapters.smtp_email_sender"):
        callback_resp = client.get(f"/auth/google/callback?code=fake-code&state={state}")

    assert callback_resp.status_code == 307
    logged = [record.getMessage() for record in caplog.records]
    assert any(
        "admin@example.com" in message and "Technician access request" in message
        for message in logged
    ), f"no admin alert email observed; log records: {logged}"


# ---------------------------------------------------------------------------
# 3b. PKCE: the verifier minted at login must reach the token exchange
# ---------------------------------------------------------------------------


def test_callback_propagates_pkce_code_verifier_to_token_exchange(pg_session_factory):
    """The flow handed to fetch_token must carry the code_verifier minted at login.

    authorization_url() sends Google a PKCE code_challenge, so the token exchange must present the
    matching code_verifier. Login and callback build independent Flow objects, so the verifier has
    to ride the session across the redirect — without it Google rejects the exchange with
    invalid_grant "Missing code verifier".
    """
    settings = _settings_with_google(os.environ["DATABASE_URL"])
    identity = _fake_identity()
    app = create_app(session_factory=pg_session_factory, settings=settings)

    seen = {}

    def capturing_exchange(flow, code: str) -> str:
        seen["code_verifier"] = flow.code_verifier
        return "fake-id-token"

    app.state.token_exchange_override = capturing_exchange
    app.state.auth_adapter_override = _make_fake_auth_adapter(identity)

    client = TestClient(app, follow_redirects=False)

    login_resp = client.get("/auth/google/login")
    from urllib.parse import parse_qs, urlparse

    location = login_resp.headers["location"]
    assert "code_challenge=" in location  # PKCE is active on the login redirect
    state = parse_qs(urlparse(location).query)["state"][0]

    callback_resp = client.get(f"/auth/google/callback?code=fake-code&state={state}")

    assert callback_resp.status_code == 307
    assert seen["code_verifier"], "callback flow reached token exchange without a PKCE code_verifier"


# ---------------------------------------------------------------------------
# 3c. Token exchange tolerates Google normalising the granted OIDC scopes
# ---------------------------------------------------------------------------


def test_real_token_exchange_tolerates_google_scope_normalization(monkeypatch):
    """The real exchange must not crash when Google returns scopes in expanded/reordered form.

    Google always normalises the granted OIDC scopes (email -> .../userinfo.email, profile ->
    .../userinfo.profile, reordered with openid), so they never byte-match the requested
    "openid email profile". oauthlib raises on any such mismatch unless the exchange relaxes that
    check, so without the relaxation every real sign-in fails the token exchange.
    """
    import json

    import requests
    from requests_oauthlib import OAuth2Session

    from fsm.platform.api.auth_routes import _build_flow, _real_token_exchange

    settings = _settings_with_google("postgresql+psycopg://unused:unused@localhost/unused")
    token_body = json.dumps(
        {
            "access_token": "fake-access-token",
            "token_type": "Bearer",
            "id_token": "the-id-token",
            "expires_in": 3599,
            "scope": "https://www.googleapis.com/auth/userinfo.email openid "
            "https://www.googleapis.com/auth/userinfo.profile",
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

    flow = _build_flow(settings, settings.google_redirect_uri)
    assert _real_token_exchange(flow, "fake-code") == "the-id-token"


# ---------------------------------------------------------------------------
# 4. Callback with bad/mismatched state → 400
# ---------------------------------------------------------------------------


def test_callback_with_bad_state_returns_400(pg_session_factory):
    settings = _settings_with_google(os.environ["DATABASE_URL"])
    identity = _fake_identity()
    app = create_app(session_factory=pg_session_factory, settings=settings)
    app.state.token_exchange_override = _make_fake_token_exchange()
    app.state.auth_adapter_override = _make_fake_auth_adapter(identity)

    client = TestClient(app, follow_redirects=False)

    # Initiate login to get a session, but provide a wrong state in the callback
    client.get("/auth/google/login")
    response = client.get("/auth/google/callback?code=fake-code&state=wrong-state-value")

    assert response.status_code == 400
    assert "state" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 5. /auth/me returns 401 when no session
# ---------------------------------------------------------------------------


def test_me_returns_401_without_session(pg_session_factory):
    settings = _settings_with_google(os.environ["DATABASE_URL"])
    app = create_app(session_factory=pg_session_factory, settings=settings)
    client = TestClient(app, follow_redirects=False)

    response = client.get("/auth/me")
    assert response.status_code == 401


def test_me_propagates_unexpected_repository_error(pg_session_factory, monkeypatch):
    """An infrastructure failure while loading the session user must not be masked as a 401."""
    client = _signed_in_client(pg_session_factory)

    from fsm.identity.adapters.repositories import SqlAlchemyUserRepository

    def _boom(self, user_id):
        raise RuntimeError("db exploded")

    monkeypatch.setattr(SqlAlchemyUserRepository, "get", _boom)

    with pytest.raises(RuntimeError):
        client.get("/auth/me")


# ---------------------------------------------------------------------------
# Profile: GET fields + PATCH /auth/me
# ---------------------------------------------------------------------------


def _signed_in_client(pg_session_factory) -> TestClient:
    """Client whose session is signed in through the full callback flow with fake Google seams."""
    settings = _settings_with_google(os.environ["DATABASE_URL"])
    app = create_app(session_factory=pg_session_factory, settings=settings)
    app.state.token_exchange_override = _make_fake_token_exchange("fake-id-token")
    app.state.auth_adapter_override = _make_fake_auth_adapter(_fake_identity())
    client = TestClient(app, follow_redirects=False)

    login_resp = client.get("/auth/google/login")
    from urllib.parse import parse_qs, urlparse

    state = parse_qs(urlparse(login_resp.headers["location"]).query)["state"][0]
    callback = client.get(f"/auth/google/callback?code=fake-code&state={state}")
    assert callback.status_code == 307
    return client


class TestProfileEndpoints:
    def test_patch_me_requires_authentication(self, pg_session_factory):
        settings = _settings_with_google(os.environ["DATABASE_URL"])
        app = create_app(session_factory=pg_session_factory, settings=settings)
        client = TestClient(app)
        assert client.patch("/auth/me", json={"address": "12 Main St"}).status_code == 401

    def test_patch_sets_fields_and_me_returns_them(self, pg_session_factory):
        client = _signed_in_client(pg_session_factory)
        resp = client.patch(
            "/auth/me",
            json={"display_name": "Dana", "address": "12 Main St", "phone": "054-1234567"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["display_name"] == "Dana"
        assert body["address"] == "12 Main St"
        assert body["phone"] == "054-1234567"
        assert body["name"]  # Google-synced name is always present

        me = client.get("/auth/me").json()
        assert me["display_name"] == "Dana"
        assert me["address"] == "12 Main St"
        assert me["phone"] == "054-1234567"

    def test_absent_field_is_left_unchanged(self, pg_session_factory):
        client = _signed_in_client(pg_session_factory)
        client.patch("/auth/me", json={"display_name": "Dana", "address": "12 Main St"})
        resp = client.patch("/auth/me", json={"address": "5 Oak Ave"})
        body = resp.json()
        assert body["address"] == "5 Oak Ave"
        assert body["display_name"] == "Dana"

    def test_empty_or_whitespace_field_clears_to_null(self, pg_session_factory):
        client = _signed_in_client(pg_session_factory)
        client.patch("/auth/me", json={"display_name": "Dana", "phone": "054-1234567"})
        resp = client.patch("/auth/me", json={"display_name": "", "phone": "   "})
        body = resp.json()
        assert body["display_name"] is None
        assert body["phone"] is None

    def test_values_are_stripped_before_storage(self, pg_session_factory):
        client = _signed_in_client(pg_session_factory)
        resp = client.patch("/auth/me", json={"address": "  12 Main St  "})
        assert resp.json()["address"] == "12 Main St"

    def test_over_length_field_is_rejected(self, pg_session_factory):
        client = _signed_in_client(pg_session_factory)
        assert client.patch("/auth/me", json={"display_name": "x" * 121}).status_code == 422
        assert client.patch("/auth/me", json={"address": "x" * 501}).status_code == 422
        assert client.patch("/auth/me", json={"phone": "x" * 41}).status_code == 422

    def test_malformed_phone_is_rejected(self, pg_session_factory):
        client = _signed_in_client(pg_session_factory)
        # Only 5 digits — not a plausible phone in any country — is rejected, nothing persisted.
        resp = client.patch("/auth/me", json={"phone": "12345"})
        assert resp.status_code == 422
        assert client.get("/auth/me").json()["phone"] is None

    def test_valid_international_phone_is_accepted(self, pg_session_factory):
        client = _signed_in_client(pg_session_factory)
        # A non-Israeli but well-formed number is accepted server-side (the UI warns, never blocks).
        resp = client.patch("/auth/me", json={"phone": "+1-202-555-0143"})
        assert resp.status_code == 200
        assert resp.json()["phone"] == "+1-202-555-0143"
