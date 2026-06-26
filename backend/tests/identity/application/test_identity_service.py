"""Tests for IdentityService application use cases."""
from __future__ import annotations

from uuid import UUID

import pytest

from fsm.identity.application import IdentityService
from fsm.identity.domain.errors import AuthenticationError, DuplicateGoogleSub, NotFoundError
from fsm.identity.domain.role import Role
from fsm.identity.domain.user import User
from fsm.identity.ports.auth import VerifiedIdentity
from tests.identity.fakes import FakeAuthPort, InMemoryUserRepository

_FIXED_ID = UUID("00000000-0000-0000-0000-000000000001")
_CREDENTIAL = "valid-token"
_IDENTITY = VerifiedIdentity(google_sub="sub-123", email="alice@example.com", name="Alice")


@pytest.fixture
def repo() -> InMemoryUserRepository:
    return InMemoryUserRepository()


@pytest.fixture
def auth() -> FakeAuthPort:
    port = FakeAuthPort()
    port.register(_CREDENTIAL, _IDENTITY)
    return port


@pytest.fixture
def service(auth: FakeAuthPort, repo: InMemoryUserRepository) -> IdentityService:
    return IdentityService(auth=auth, users=repo, new_id=lambda: _FIXED_ID)


class _RacingRepo(InMemoryUserRepository):
    """Simulates a concurrent first-sign-in race.

    The first get_by_google_sub returns None (both concurrent requests see an empty table).
    add() raises DuplicateGoogleSub (the concurrent winner committed first).
    Subsequent get_by_google_sub calls return the pre-populated winning user.
    """

    def __init__(self, existing_user: User) -> None:
        super().__init__()
        self._existing_user = existing_user
        self._lookup_calls = 0

    def add(self, user: User) -> None:
        raise DuplicateGoogleSub("concurrent insert committed first")

    def get_by_google_sub(self, google_sub: str) -> User | None:
        self._lookup_calls += 1
        if self._lookup_calls == 1:
            return None  # first call: race not yet detected
        if google_sub == self._existing_user.google_sub:
            return self._existing_user
        return super().get_by_google_sub(google_sub)


class TestSignInWithGoogle:
    def test_first_sign_in_creates_customer_user(
        self, service: IdentityService, repo: InMemoryUserRepository
    ) -> None:
        user = service.sign_in_with_google(_CREDENTIAL)

        assert user.id == _FIXED_ID
        assert user.google_sub == _IDENTITY.google_sub
        assert user.email == _IDENTITY.email
        assert user.name == _IDENTITY.name
        assert user.role == Role.CUSTOMER
        assert repo.get(_FIXED_ID) is user

    def test_second_sign_in_returns_same_user(
        self, service: IdentityService, repo: InMemoryUserRepository
    ) -> None:
        first = service.sign_in_with_google(_CREDENTIAL)
        second = service.sign_in_with_google(_CREDENTIAL)

        assert second.id == first.id
        assert len(repo.get_all()) == 1

    def test_second_sign_in_updates_changed_claims(
        self, auth: FakeAuthPort, repo: InMemoryUserRepository
    ) -> None:
        svc = IdentityService(auth=auth, users=repo, new_id=lambda: _FIXED_ID)
        svc.sign_in_with_google(_CREDENTIAL)

        updated = VerifiedIdentity(
            google_sub=_IDENTITY.google_sub,
            email="alice-new@example.com",
            name="Alice Updated",
        )
        auth.register(_CREDENTIAL, updated)
        user = svc.sign_in_with_google(_CREDENTIAL)

        assert user.id == _FIXED_ID
        assert user.email == "alice-new@example.com"
        assert user.name == "Alice Updated"
        assert repo.get_by_google_sub(_IDENTITY.google_sub).email == "alice-new@example.com"

    def test_invalid_credential_raises_authentication_error_and_creates_no_user(
        self, service: IdentityService, repo: InMemoryUserRepository
    ) -> None:
        with pytest.raises(AuthenticationError):
            service.sign_in_with_google("bad-token")

        assert len(repo.get_all()) == 0

    def test_concurrent_first_sign_in_race_resolves_to_existing_user(
        self, auth: FakeAuthPort
    ) -> None:
        existing = User(
            id=_FIXED_ID,
            google_sub=_IDENTITY.google_sub,
            email=_IDENTITY.email,
            name=_IDENTITY.name,
            role=Role.CUSTOMER,
        )
        racing_repo = _RacingRepo(existing_user=existing)
        svc = IdentityService(auth=auth, users=racing_repo, new_id=lambda: _FIXED_ID)

        result = svc.sign_in_with_google(_CREDENTIAL)

        assert result is existing


class TestRepeatSignInSaveBehavior:
    def test_repeat_sign_in_with_identical_claims_does_not_call_save(
        self, auth: FakeAuthPort, repo: InMemoryUserRepository
    ) -> None:
        svc = IdentityService(auth=auth, users=repo, new_id=lambda: _FIXED_ID)
        svc.sign_in_with_google(_CREDENTIAL)
        save_count_after_first = repo.save_count

        svc.sign_in_with_google(_CREDENTIAL)

        assert repo.save_count == save_count_after_first

    def test_repeat_sign_in_with_changed_email_calls_save(
        self, auth: FakeAuthPort, repo: InMemoryUserRepository
    ) -> None:
        svc = IdentityService(auth=auth, users=repo, new_id=lambda: _FIXED_ID)
        svc.sign_in_with_google(_CREDENTIAL)

        updated = VerifiedIdentity(
            google_sub=_IDENTITY.google_sub,
            email="alice-new@example.com",
            name=_IDENTITY.name,
        )
        auth.register(_CREDENTIAL, updated)
        svc.sign_in_with_google(_CREDENTIAL)

        assert repo.save_count == 1

    def test_repeat_sign_in_with_changed_name_calls_save(
        self, auth: FakeAuthPort, repo: InMemoryUserRepository
    ) -> None:
        svc = IdentityService(auth=auth, users=repo, new_id=lambda: _FIXED_ID)
        svc.sign_in_with_google(_CREDENTIAL)

        updated = VerifiedIdentity(
            google_sub=_IDENTITY.google_sub,
            email=_IDENTITY.email,
            name="Alice Renamed",
        )
        auth.register(_CREDENTIAL, updated)
        svc.sign_in_with_google(_CREDENTIAL)

        assert repo.save_count == 1


class TestAssignRole:
    def test_assign_role_promotes_user_and_persists(
        self, service: IdentityService, repo: InMemoryUserRepository
    ) -> None:
        service.sign_in_with_google(_CREDENTIAL)

        updated = service.assign_role(_FIXED_ID, Role.TECHNICIAN)

        assert updated.role == Role.TECHNICIAN
        assert repo.get(_FIXED_ID).role == Role.TECHNICIAN

    def test_assign_role_unknown_id_raises_not_found(
        self, service: IdentityService
    ) -> None:
        unknown = UUID("00000000-0000-0000-0000-000000000099")
        with pytest.raises(NotFoundError):
            service.assign_role(unknown, Role.TECHNICIAN)
