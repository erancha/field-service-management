"""Port contract tests for in-memory fake implementations.

These tests verify that each fake honours the protocol contract. They double
as the contract test suite that any future concrete adapter must also satisfy.
"""
from __future__ import annotations

import uuid

import pytest

from fsm.identity.domain import NotFoundError, Role, RoleStatus, User
from fsm.identity.domain.errors import AuthenticationError
from fsm.identity.ports import AuthPort, UserRepository, VerifiedIdentity
from tests.identity.fakes import FakeAuthPort, InMemoryUserRepository


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(*, google_sub: str = "sub-001", email: str = "a@example.com") -> User:
    return User(
        id=uuid.uuid4(),
        google_sub=google_sub,
        email=email,
        name="Alice",
        role=Role.CUSTOMER,
        role_status=RoleStatus.APPROVED,
    )


# ---------------------------------------------------------------------------
# InMemoryUserRepository
# ---------------------------------------------------------------------------

class TestInMemoryUserRepository:
    def test_add_then_get_by_google_sub_round_trips(self):
        repo = InMemoryUserRepository()
        user = _make_user(google_sub="sub-abc")
        repo.add(user)
        fetched = repo.get_by_google_sub("sub-abc")
        assert fetched is user

    def test_get_by_google_sub_returns_none_for_unknown_sub(self):
        repo = InMemoryUserRepository()
        assert repo.get_by_google_sub("unknown-sub") is None

    def test_get_raises_not_found_for_unknown_id(self):
        repo = InMemoryUserRepository()
        with pytest.raises(NotFoundError):
            repo.get(uuid.uuid4())

    def test_save_updates_stored_user(self):
        repo = InMemoryUserRepository()
        user = _make_user()
        repo.add(user)
        user.request_role(Role.TECHNICIAN)
        repo.save(user)
        assert repo.get(user.id).role is Role.TECHNICIAN

    def test_get_returns_added_user_by_id(self):
        repo = InMemoryUserRepository()
        user = _make_user()
        repo.add(user)
        assert repo.get(user.id) is user

    def test_isinstance_satisfies_protocol(self):
        assert isinstance(InMemoryUserRepository(), UserRepository)


# ---------------------------------------------------------------------------
# FakeAuthPort
# ---------------------------------------------------------------------------

class TestFakeAuthPort:
    def test_registered_credential_returns_verified_identity(self):
        auth = FakeAuthPort()
        identity = VerifiedIdentity(google_sub="sub-001", email="a@example.com", name="Alice")
        auth.register("valid-token", identity)
        assert auth.verify("valid-token") == identity

    def test_unregistered_credential_raises_authentication_error(self):
        auth = FakeAuthPort()
        with pytest.raises(AuthenticationError):
            auth.verify("bad-token")

    def test_isinstance_satisfies_protocol(self):
        assert isinstance(FakeAuthPort(), AuthPort)
