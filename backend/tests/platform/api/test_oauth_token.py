"""Unit tests for the shared authorization-code exchange in oauth_token.

These exercise the scope-relaxation lifecycle around flow.fetch_token without a real Google flow.
"""
from __future__ import annotations

import os

from fsm.platform.api.oauth_token import fetch_token_relaxed


class _FakeFlow:
    """Records the environment observed during fetch_token so the test can assert on it."""

    def __init__(self, on_exchange):
        self._on_exchange = on_exchange

    def fetch_token(self, code):
        self._on_exchange(code)


def test_relaxation_is_active_during_exchange_and_cleared_afterwards(monkeypatch):
    """The relaxation is set only for the duration of the exchange, then the prior env is restored."""
    monkeypatch.delenv("OAUTHLIB_RELAX_TOKEN_SCOPE", raising=False)

    seen = {}

    def _during_exchange(code):
        seen["code"] = code
        seen["relaxed"] = os.environ.get("OAUTHLIB_RELAX_TOKEN_SCOPE")

    fetch_token_relaxed(_FakeFlow(_during_exchange), "fake-code")

    assert seen["code"] == "fake-code"
    assert seen["relaxed"] == "1"
    assert "OAUTHLIB_RELAX_TOKEN_SCOPE" not in os.environ


def test_a_preexisting_relaxation_value_is_restored(monkeypatch):
    """An externally configured value is left untouched, not clobbered to the default or dropped."""
    monkeypatch.setenv("OAUTHLIB_RELAX_TOKEN_SCOPE", "external")

    fetch_token_relaxed(_FakeFlow(lambda code: None), "fake-code")

    assert os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] == "external"
