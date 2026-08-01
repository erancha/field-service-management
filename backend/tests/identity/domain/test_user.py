"""Tests for the User entity."""
from __future__ import annotations

import datetime as dt
import uuid

import pytest

from fsm.identity.domain import InvalidUser, Role, RoleStatus, User


def _new_user(**kwargs) -> User:
    defaults = dict(
        id=uuid.uuid4(),
        google_sub="google-sub-1234567890",
        email="alice@example.com",
        name="Alice",
        role=Role.CUSTOMER,
        role_status=RoleStatus.APPROVED,
    )
    defaults.update(kwargs)
    return User(**defaults)


class TestUserCreation:
    def test_creates_valid_user(self):
        user = _new_user()
        assert user.email == "alice@example.com"
        assert user.role == Role.CUSTOMER

    def test_carries_role_status(self):
        user = _new_user(role=Role.TECHNICIAN, role_status=RoleStatus.PENDING)
        assert user.role_status == RoleStatus.PENDING

    def test_decision_fields_default_to_none(self):
        user = _new_user()
        assert user.role_decided_at is None
        assert user.role_decided_by is None

    def test_fields_accessible(self):
        uid = uuid.uuid4()
        user = _new_user(id=uid, name="Bob")
        assert user.id == uid
        assert user.name == "Bob"

    def test_empty_google_sub_raises(self):
        with pytest.raises(InvalidUser):
            _new_user(google_sub="")

    def test_empty_email_raises(self):
        with pytest.raises(InvalidUser):
            _new_user(email="")


class TestGrantRole:
    def test_grant_sets_role_and_approves_immediately(self):
        user = _new_user(role=Role.TECHNICIAN, role_status=RoleStatus.PENDING)
        user.grant_role(Role.CUSTOMER)
        assert user.role == Role.CUSTOMER
        assert user.role_status == RoleStatus.APPROVED

    def test_grant_clears_prior_decision_stamps(self):
        user = _new_user(
            role=Role.TECHNICIAN,
            role_status=RoleStatus.REJECTED,
            role_decided_at=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
            role_decided_by=uuid.uuid4(),
        )
        user.grant_role(Role.CUSTOMER)
        assert user.role_decided_at is None
        assert user.role_decided_by is None


class TestRequestRole:
    def test_request_sets_role_pending(self):
        user = _new_user(role=Role.CUSTOMER, role_status=RoleStatus.APPROVED)
        user.request_role(Role.TECHNICIAN)
        assert user.role == Role.TECHNICIAN
        assert user.role_status == RoleStatus.PENDING


class TestRoleDecision:
    def test_approve_sets_approved_and_stamps_decision(self):
        admin_id = uuid.uuid4()
        at = dt.datetime(2026, 6, 26, 12, 0, tzinfo=dt.timezone.utc)
        user = _new_user(role=Role.TECHNICIAN, role_status=RoleStatus.PENDING)

        user.approve(decided_by=admin_id, at=at)

        assert user.role_status == RoleStatus.APPROVED
        assert user.role_decided_by == admin_id
        assert user.role_decided_at == at

    def test_reject_sets_rejected_and_stamps_decision(self):
        admin_id = uuid.uuid4()
        at = dt.datetime(2026, 6, 26, 12, 0, tzinfo=dt.timezone.utc)
        user = _new_user(role=Role.TECHNICIAN, role_status=RoleStatus.PENDING)

        user.reject(decided_by=admin_id, at=at)

        assert user.role_status == RoleStatus.REJECTED
        assert user.role_decided_by == admin_id
        assert user.role_decided_at == at


def _make_user(**overrides) -> User:
    defaults = dict(
        id=uuid.uuid4(),
        google_sub="sub-1",
        email="a@example.com",
        name="Google Name",
        role=Role.CUSTOMER,
        role_status=RoleStatus.APPROVED,
    )
    defaults.update(overrides)
    return User(**defaults)


def test_profile_fields_default_to_none() -> None:
    user = _make_user()
    assert user.display_name is None
    assert user.address is None
    assert user.phone is None
    assert user.assist_disclaimer_accepted_at is None


def test_accepting_the_assist_disclaimer_stamps_the_moment() -> None:
    user = _make_user()
    at = dt.datetime(2026, 8, 1, 9, 0, tzinfo=dt.timezone.utc)
    user.accept_assist_disclaimer(at)
    assert user.assist_disclaimer_accepted_at == at


def test_accepting_the_assist_disclaimer_again_keeps_the_first_moment() -> None:
    user = _make_user()
    first = dt.datetime(2026, 8, 1, 9, 0, tzinfo=dt.timezone.utc)
    user.accept_assist_disclaimer(first)
    user.accept_assist_disclaimer(first + dt.timedelta(days=30))
    assert user.assist_disclaimer_accepted_at == first


def test_preferred_name_prefers_display_name() -> None:
    assert _make_user(display_name="Dana").preferred_name == "Dana"


def test_preferred_name_falls_back_to_google_name() -> None:
    assert _make_user().preferred_name == "Google Name"
