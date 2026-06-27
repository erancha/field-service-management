"""Tests for IdentityService application use cases.

Sign-in is host-aware: the deployment a process serves (SignInHost) decides the role and
approval status assigned on sign-in. Customer access is granted immediately; technician access
is requested PENDING and needs back-office approval; the back-office host grants ADMIN only to a
configured email allowlist and refuses everyone else.
"""
from __future__ import annotations

import datetime as dt
from uuid import UUID

import pytest

from fsm.identity.application import IdentityService, SignInHost
from fsm.identity.domain.errors import (
    AuthenticationError,
    BackOfficeAccessDenied,
    InvalidRoleDecision,
    NotFoundError,
)
from fsm.identity.domain.role import Role
from fsm.identity.domain.role_status import RoleStatus
from fsm.identity.domain.user import User
from fsm.identity.ports.auth import VerifiedIdentity
from tests.identity.fakes import FakeAuthPort, InMemoryUserRepository

_FIXED_ID = UUID("00000000-0000-0000-0000-000000000001")
_ADMIN_ID = UUID("00000000-0000-0000-0000-0000000000aa")
_CREDENTIAL = "valid-token"
_IDENTITY = VerifiedIdentity(google_sub="sub-123", email="alice@example.com", name="Alice")
_FIXED_NOW = dt.datetime(2026, 6, 26, 12, 0, tzinfo=dt.timezone.utc)
_ADMIN_EMAILS = frozenset({"boss@example.com"})


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
    return IdentityService(
        auth=auth, users=repo, new_id=lambda: _FIXED_ID, now=lambda: _FIXED_NOW
    )


def _sign_in(service: IdentityService, host: SignInHost) -> User:
    return service.sign_in(_CREDENTIAL, host=host, admin_emails=_ADMIN_EMAILS).user


class TestSignInHostAssignment:
    def test_new_user_on_customer_host_is_approved_customer(self, service, repo):
        user = _sign_in(service, SignInHost.CUSTOMER)
        assert user.role == Role.CUSTOMER
        assert user.role_status == RoleStatus.APPROVED
        assert repo.get(_FIXED_ID).role_status == RoleStatus.APPROVED

    def test_new_user_on_technician_host_is_pending_technician(self, service, repo):
        user = _sign_in(service, SignInHost.TECHNICIAN)
        assert user.role == Role.TECHNICIAN
        assert user.role_status == RoleStatus.PENDING

    def test_new_user_on_backoffice_host_with_allowlisted_email_is_admin(self, auth, repo):
        auth.register("boss-token", VerifiedIdentity("sub-boss", "boss@example.com", "Boss"))
        svc = IdentityService(auth=auth, users=repo, new_id=lambda: _FIXED_ID, now=lambda: _FIXED_NOW)
        user = svc.sign_in("boss-token", host=SignInHost.BACKOFFICE, admin_emails=_ADMIN_EMAILS).user
        assert user.role == Role.ADMIN
        assert user.role_status == RoleStatus.APPROVED

    def test_new_user_on_backoffice_host_without_allowlist_is_refused_and_not_persisted(
        self, service, repo
    ):
        with pytest.raises(BackOfficeAccessDenied):
            _sign_in(service, SignInHost.BACKOFFICE)
        assert repo.get_all() == []


class TestSignInHostReassignment:
    def test_customer_signing_in_on_technician_host_becomes_pending_technician(self, service):
        _sign_in(service, SignInHost.CUSTOMER)
        user = _sign_in(service, SignInHost.TECHNICIAN)
        assert user.role == Role.TECHNICIAN
        assert user.role_status == RoleStatus.PENDING

    def test_pending_technician_repeats_on_technician_host_stays_pending(self, service):
        _sign_in(service, SignInHost.TECHNICIAN)
        user = _sign_in(service, SignInHost.TECHNICIAN)
        assert user.role_status == RoleStatus.PENDING

    def test_approved_technician_on_technician_host_stays_approved(self, service):
        _sign_in(service, SignInHost.TECHNICIAN)
        service.approve_technician(_FIXED_ID, decided_by=_ADMIN_ID)
        user = _sign_in(service, SignInHost.TECHNICIAN)
        assert user.role == Role.TECHNICIAN
        assert user.role_status == RoleStatus.APPROVED

    def test_rejected_technician_on_technician_host_stays_rejected_sticky(self, service):
        _sign_in(service, SignInHost.TECHNICIAN)
        service.reject_technician(_FIXED_ID, decided_by=_ADMIN_ID)
        user = _sign_in(service, SignInHost.TECHNICIAN)
        assert user.role_status == RoleStatus.REJECTED

    def test_pending_technician_on_customer_host_silently_becomes_customer(self, service):
        _sign_in(service, SignInHost.TECHNICIAN)
        user = _sign_in(service, SignInHost.CUSTOMER)
        assert user.role == Role.CUSTOMER
        assert user.role_status == RoleStatus.APPROVED


class TestSignInOutcomeFlags:
    def _outcome(self, service, host):
        return service.sign_in(_CREDENTIAL, host=host, admin_emails=_ADMIN_EMAILS)

    def test_new_technician_request_flags_requested_pending(self, service):
        outcome = self._outcome(service, SignInHost.TECHNICIAN)
        assert outcome.requested_pending is True
        assert outcome.withdrew_pending is False

    def test_repeat_pending_technician_flags_nothing(self, service):
        self._outcome(service, SignInHost.TECHNICIAN)
        outcome = self._outcome(service, SignInHost.TECHNICIAN)
        assert outcome.requested_pending is False
        assert outcome.withdrew_pending is False

    def test_pending_technician_switching_to_customer_flags_withdrew(self, service):
        self._outcome(service, SignInHost.TECHNICIAN)
        outcome = self._outcome(service, SignInHost.CUSTOMER)
        assert outcome.withdrew_pending is True
        assert outcome.requested_pending is False

    def test_plain_customer_sign_in_flags_nothing(self, service):
        outcome = self._outcome(service, SignInHost.CUSTOMER)
        assert outcome.requested_pending is False
        assert outcome.withdrew_pending is False


class TestSignInClaimsAndErrors:
    def test_second_sign_in_updates_changed_claims(self, auth, repo):
        svc = IdentityService(auth=auth, users=repo, new_id=lambda: _FIXED_ID, now=lambda: _FIXED_NOW)
        svc.sign_in(_CREDENTIAL, host=SignInHost.CUSTOMER, admin_emails=_ADMIN_EMAILS)
        auth.register(_CREDENTIAL, VerifiedIdentity(_IDENTITY.google_sub, "new@example.com", "New"))
        user = svc.sign_in(_CREDENTIAL, host=SignInHost.CUSTOMER, admin_emails=_ADMIN_EMAILS).user
        assert user.email == "new@example.com"
        assert user.name == "New"

    def test_repeat_sign_in_same_host_unchanged_does_not_save(self, auth, repo):
        svc = IdentityService(auth=auth, users=repo, new_id=lambda: _FIXED_ID, now=lambda: _FIXED_NOW)
        svc.sign_in(_CREDENTIAL, host=SignInHost.CUSTOMER, admin_emails=_ADMIN_EMAILS)
        saves_after_first = repo.save_count
        svc.sign_in(_CREDENTIAL, host=SignInHost.CUSTOMER, admin_emails=_ADMIN_EMAILS)
        assert repo.save_count == saves_after_first

    def test_invalid_credential_raises_and_creates_no_user(self, service, repo):
        with pytest.raises(AuthenticationError):
            service.sign_in("bad-token", host=SignInHost.CUSTOMER, admin_emails=_ADMIN_EMAILS)
        assert repo.get_all() == []


class TestApproveRejectTechnician:
    def test_approve_pending_technician_sets_approved_and_stamps(self, service, repo):
        _sign_in(service, SignInHost.TECHNICIAN)
        user = service.approve_technician(_FIXED_ID, decided_by=_ADMIN_ID)
        assert user.role_status == RoleStatus.APPROVED
        assert user.role_decided_by == _ADMIN_ID
        assert user.role_decided_at == _FIXED_NOW
        assert repo.get(_FIXED_ID).role_status == RoleStatus.APPROVED

    def test_reject_pending_technician_sets_rejected_and_stamps(self, service, repo):
        _sign_in(service, SignInHost.TECHNICIAN)
        user = service.reject_technician(_FIXED_ID, decided_by=_ADMIN_ID)
        assert user.role_status == RoleStatus.REJECTED
        assert user.role_decided_by == _ADMIN_ID

    def test_approve_unknown_user_raises_not_found(self, service):
        with pytest.raises(NotFoundError):
            service.approve_technician(_FIXED_ID, decided_by=_ADMIN_ID)

    def test_approve_non_pending_technician_raises_invalid_decision(self, service):
        _sign_in(service, SignInHost.CUSTOMER)
        with pytest.raises(InvalidRoleDecision):
            service.approve_technician(_FIXED_ID, decided_by=_ADMIN_ID)


class TestListPendingTechnicians:
    def test_lists_only_pending_technicians(self, auth, repo):
        svc = IdentityService(auth=auth, users=repo, new_id=lambda: _FIXED_ID, now=lambda: _FIXED_NOW)
        svc.sign_in(_CREDENTIAL, host=SignInHost.TECHNICIAN, admin_emails=_ADMIN_EMAILS)

        auth.register("c-token", VerifiedIdentity("sub-c", "c@example.com", "Cust"))
        svc2 = IdentityService(
            auth=auth, users=repo,
            new_id=lambda: UUID("00000000-0000-0000-0000-0000000000c0"),
            now=lambda: _FIXED_NOW,
        )
        svc2.sign_in("c-token", host=SignInHost.CUSTOMER, admin_emails=_ADMIN_EMAILS)

        pending = svc.list_pending_technicians()
        assert [u.id for u in pending] == [_FIXED_ID]
