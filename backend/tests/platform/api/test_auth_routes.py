"""Integration tests for Google OAuth / session auth endpoints.

A Postgres 16 container is started once per module. Alembic migrations are
applied to it once. The injectable seams (token_exchange_override and
auth_adapter_override on app.state) let the full callback→user→session path
run against real PG without hitting real Google.
"""
from __future__ import annotations

import os
import uuid
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


def _settings_with_google(pg_url: str) -> Settings:
    return Settings(
        database_url=pg_url,
        app_env="test",
        google_client_id="test-client-id.apps.googleusercontent.com",
        google_client_secret="test-client-secret",
        google_redirect_uri="http://localhost:8001/auth/google/callback",
        session_secret="test-session-secret-32-bytes-long!!",
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
