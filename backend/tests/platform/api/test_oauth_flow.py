"""Unit tests for the shared Google OAuth flow plumbing (fsm.platform.api.oauth_flow).

Pins the contract both OAuth routers (sign-in and calendar connect) build on: one definition
of the Google endpoint URIs, a Flow built from in-memory client config parameterized by
scopes, and the state + PKCE session choreography parameterized only by a session-key prefix.
No network or database is involved; a SimpleNamespace stands in for the request because the
helpers touch nothing beyond request.session and request.app.state.
"""
from __future__ import annotations

import inspect
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from fsm.platform.config import Settings


def _settings() -> Settings:
    return Settings(
        database_url="postgresql+psycopg://unused:unused@localhost/unused",
        app_env="test",
        google_client_id="test-client-id.apps.googleusercontent.com",
        google_client_secret="test-client-secret",
        google_redirect_uri="http://localhost:8001/auth/google/callback",
        session_secret="test-session-secret-32-bytes-long!!",
    )


def _request() -> SimpleNamespace:
    return SimpleNamespace(session={})


def test_calendar_client_factory_defaults_to_the_shared_token_uri():
    from fsm.calendar.adapters.client_factory import build_calendar_client
    from fsm.platform.google_oauth import GOOGLE_TOKEN_URI

    default = inspect.signature(build_calendar_client).parameters["token_uri"].default
    assert default == GOOGLE_TOKEN_URI


def test_build_flow_uses_shared_endpoints_and_given_scopes():
    from fsm.platform.api.oauth_flow import build_flow
    from fsm.platform.google_oauth import GOOGLE_AUTH_URI, GOOGLE_TOKEN_URI

    settings = _settings()
    flow = build_flow(settings, settings.google_redirect_uri, scopes=("openid", "email"))

    assert flow.client_config["auth_uri"] == GOOGLE_AUTH_URI
    assert flow.client_config["token_uri"] == GOOGLE_TOKEN_URI
    assert flow.client_config["client_id"] == settings.google_client_id
    assert flow.oauth2session.scope == ["openid", "email"]
    assert flow.redirect_uri == settings.google_redirect_uri


def test_begin_authorization_stores_state_and_verifier_under_the_prefix():
    from fsm.platform.api.oauth_flow import begin_authorization, build_flow

    settings = _settings()
    flow = build_flow(settings, settings.google_redirect_uri, scopes=("openid",))
    request = _request()

    response = begin_authorization(request, flow, "calendar_", prompt="consent")

    assert response.status_code == 307
    params = parse_qs(urlparse(response.headers["location"]).query)
    assert params["state"] == [request.session["calendar_oauth_state"]]
    assert request.session["calendar_code_verifier"] == flow.code_verifier
    assert params["access_type"] == ["offline"]
    assert params["include_granted_scopes"] == ["true"]
    assert params["prompt"] == ["consent"]
    assert "code_challenge" in params


def test_state_matches_only_the_state_minted_at_login():
    from fsm.platform.api.oauth_flow import state_matches

    request = _request()
    request.session["oauth_state"] = "expected-state"

    assert state_matches(request, "expected-state", "")
    assert not state_matches(request, "tampered-state", "")
    assert not state_matches(_request(), "expected-state", "")


def test_restore_code_verifier_and_clear_flow_session():
    from fsm.platform.api.oauth_flow import clear_flow_session, restore_code_verifier

    request = _request()
    request.session["calendar_oauth_state"] = "state"
    request.session["calendar_code_verifier"] = "verifier"
    flow = SimpleNamespace(code_verifier=None)

    restore_code_verifier(flow, request, "calendar_")
    assert flow.code_verifier == "verifier"

    clear_flow_session(request, "calendar_")
    assert request.session == {}
    clear_flow_session(request, "calendar_")  # absent keys are not an error


def test_make_token_exchange_returns_the_named_credential():
    from fsm.platform.api.oauth_flow import make_token_exchange

    exchanged = []

    class FakeFlow:
        credentials = SimpleNamespace(refresh_token="the-refresh-token")

        def fetch_token(self, code):
            exchanged.append(code)

    exchange = make_token_exchange("refresh_token")

    assert exchange(FakeFlow(), "auth-code") == "the-refresh-token"
    assert exchanged == ["auth-code"]


def test_resolve_token_exchange_prefers_the_app_state_override():
    from fsm.platform.api.oauth_flow import resolve_token_exchange

    def default(flow, code):
        return "real"

    def override(flow, code):
        return "fake"

    app = SimpleNamespace(state=SimpleNamespace())
    assert resolve_token_exchange(app, "token_exchange_override", default) is default

    app.state.token_exchange_override = override
    assert resolve_token_exchange(app, "token_exchange_override", override) is override


def test_get_settings_prefers_app_state_over_process_settings():
    from fsm.platform.api.oauth_flow import get_settings

    settings = _settings()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=settings)))

    assert get_settings(request) is settings


def test_get_settings_falls_back_to_process_settings(monkeypatch):
    from fsm.platform.api.oauth_flow import get_settings

    fallback = _settings()
    monkeypatch.setattr("fsm.platform.config.get_settings", lambda: fallback)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))

    assert get_settings(request) is fallback


def test_get_session_factory_delegates_to_the_app_module(monkeypatch):
    from fsm.platform.api.oauth_flow import get_session_factory

    sentinel = object()
    monkeypatch.setattr("fsm.platform.app._get_session_factory", lambda app: sentinel)

    assert get_session_factory(SimpleNamespace()) is sentinel
