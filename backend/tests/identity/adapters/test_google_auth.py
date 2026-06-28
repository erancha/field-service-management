"""Unit tests for GoogleOidcAuthAdapter — no network, no real tokens."""
from __future__ import annotations

import pytest
from google.auth.exceptions import GoogleAuthError

from fsm.identity.adapters.google_auth import GoogleOidcAuthAdapter
from fsm.identity.domain.errors import AuthenticationError
from fsm.identity.ports.auth import VerifiedIdentity

_VALID_CLAIMS = {
    "sub": "google-sub-123",
    "email": "alice@example.com",
    "name": "Alice Smith",
    "email_verified": True,
}


def _make_adapter(
    claims: dict | None = None,
    *,
    raise_exc: BaseException | None = None,
) -> GoogleOidcAuthAdapter:
    def fake_verifier(credential: str, client_id: str) -> dict:
        if raise_exc is not None:
            raise raise_exc
        return claims if claims is not None else _VALID_CLAIMS

    return GoogleOidcAuthAdapter(client_id="test-client-id", verify_token=fake_verifier)


class TestGoogleOidcAuthAdapterConstruction:
    def test_empty_string_client_id_raises_value_error(self):
        with pytest.raises(ValueError, match="client_id"):
            GoogleOidcAuthAdapter(client_id="")

    def test_none_client_id_raises_value_error(self):
        with pytest.raises(ValueError, match="client_id"):
            GoogleOidcAuthAdapter(client_id=None)  # type: ignore[arg-type]


class TestGoogleOidcAuthAdapter:
    def test_valid_claims_returns_verified_identity(self):
        adapter = _make_adapter()
        result = adapter.verify("any-credential")
        assert isinstance(result, VerifiedIdentity)
        assert result.google_sub == "google-sub-123"
        assert result.email == "alice@example.com"
        assert result.name == "Alice Smith"

    def test_verifier_raising_value_error_raises_authentication_error(self):
        adapter = _make_adapter(raise_exc=ValueError("invalid token"))
        with pytest.raises(AuthenticationError):
            adapter.verify("bad-credential")

    def test_verifier_raising_google_auth_error_raises_authentication_error(self):
        adapter = _make_adapter(raise_exc=GoogleAuthError("transport error"))
        with pytest.raises(AuthenticationError):
            adapter.verify("bad-credential")

    def test_verifier_raising_other_exception_propagates(self):
        adapter = _make_adapter(raise_exc=RuntimeError("unexpected crash"))
        with pytest.raises(RuntimeError):
            adapter.verify("bad-credential")

    def test_email_verified_false_raises_authentication_error(self):
        claims = {**_VALID_CLAIMS, "email_verified": False}
        adapter = _make_adapter(claims=claims)
        with pytest.raises(AuthenticationError, match="email_verified"):
            adapter.verify("any-credential")

    def test_email_verified_missing_raises_authentication_error(self):
        claims = {k: v for k, v in _VALID_CLAIMS.items() if k != "email_verified"}
        adapter = _make_adapter(claims=claims)
        with pytest.raises(AuthenticationError, match="email_verified"):
            adapter.verify("any-credential")

    def test_claims_missing_email_raises_authentication_error(self):
        claims = {"sub": "google-sub-123", "name": "Alice Smith", "email_verified": True}
        adapter = _make_adapter(claims=claims)
        with pytest.raises(AuthenticationError, match="email"):
            adapter.verify("any-credential")

    def test_claims_missing_sub_raises_authentication_error(self):
        claims = {"email": "alice@example.com", "name": "Alice Smith", "email_verified": True}
        adapter = _make_adapter(claims=claims)
        with pytest.raises(AuthenticationError, match="sub"):
            adapter.verify("any-credential")

    def test_claims_missing_name_raises_authentication_error(self):
        claims = {"sub": "google-sub-123", "email": "alice@example.com", "email_verified": True}
        adapter = _make_adapter(claims=claims)
        with pytest.raises(AuthenticationError, match="name"):
            adapter.verify("any-credential")


def test_default_verify_allows_clock_skew(monkeypatch):
    """The default verifier must tolerate a few seconds of clock skew between this host and Google.

    Google signs ID tokens against its own clock; with zero tolerance a host running even a second
    behind rejects a freshly issued token as "used too early". The verifier passes a non-zero
    clock_skew_in_seconds so normal drift does not break sign-in.
    """
    from fsm.identity.adapters.google_auth import _default_verify

    captured = {}

    def fake_verify(credential, request, audience=None, clock_skew_in_seconds=0):
        captured["clock_skew_in_seconds"] = clock_skew_in_seconds
        return dict(_VALID_CLAIMS)

    monkeypatch.setattr("google.oauth2.id_token.verify_oauth2_token", fake_verify)

    _default_verify("a-credential", "test-client-id")

    assert captured["clock_skew_in_seconds"] >= 5
