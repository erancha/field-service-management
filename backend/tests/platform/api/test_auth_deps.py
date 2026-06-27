"""Tests for the session-auth dependencies.

require_user resolves the caller's role and approval status from the database on every request
(the session cookie carries only identity), so an approval or revocation takes effect immediately.
require_role additionally requires the role to be APPROVED.
"""
from __future__ import annotations

import types
import uuid

import pytest
from fastapi import HTTPException

from fsm.identity.domain.role import Role
from fsm.identity.domain.role_status import RoleStatus
from fsm.identity.domain.user import User
from fsm.platform.api.auth_deps import (
    SessionUser,
    require_role,
    require_user,
    resolve_current_user,
)
from tests.identity.fakes import InMemoryUserRepository


def _user(role: Role, status: RoleStatus) -> User:
    return User(
        id=uuid.uuid4(),
        google_sub="sub-1",
        email="u@example.com",
        name="U",
        role=role,
        role_status=status,
    )


class TestResolveCurrentUser:
    def test_reflects_current_role_and_status_from_repository(self):
        repo = InMemoryUserRepository()
        user = _user(Role.TECHNICIAN, RoleStatus.PENDING)
        repo.add(user)

        resolved = resolve_current_user(user.id, repo)

        assert resolved.id == user.id
        assert resolved.role == Role.TECHNICIAN
        assert resolved.role_status == RoleStatus.PENDING

    def test_unknown_user_raises_401(self):
        repo = InMemoryUserRepository()
        with pytest.raises(HTTPException) as exc:
            resolve_current_user(uuid.uuid4(), repo)
        assert exc.value.status_code == 401


class TestRequireRoleApprovedGate:
    def test_approved_allowed_role_passes(self):
        dep = require_role(Role.TECHNICIAN)
        user = SessionUser(
            id=uuid.uuid4(), role=Role.TECHNICIAN, role_status=RoleStatus.APPROVED, email=None
        )
        assert dep(user=user) is user

    def test_pending_allowed_role_is_forbidden(self):
        dep = require_role(Role.TECHNICIAN)
        user = SessionUser(
            id=uuid.uuid4(), role=Role.TECHNICIAN, role_status=RoleStatus.PENDING, email=None
        )
        with pytest.raises(HTTPException) as exc:
            dep(user=user)
        assert exc.value.status_code == 403

    def test_wrong_role_is_forbidden(self):
        dep = require_role(Role.TECHNICIAN)
        user = SessionUser(
            id=uuid.uuid4(), role=Role.CUSTOMER, role_status=RoleStatus.APPROVED, email=None
        )
        with pytest.raises(HTTPException) as exc:
            dep(user=user)
        assert exc.value.status_code == 403


class TestRequireUserSessionExtraction:
    def test_no_session_raises_401(self):
        request = types.SimpleNamespace(scope={})
        with pytest.raises(HTTPException) as exc:
            require_user(request)
        assert exc.value.status_code == 401

    def test_session_without_user_id_raises_401(self):
        request = types.SimpleNamespace(scope={"session": {}})
        with pytest.raises(HTTPException) as exc:
            require_user(request)
        assert exc.value.status_code == 401

    def test_malformed_user_id_raises_401(self):
        request = types.SimpleNamespace(scope={"session": {"user_id": "not-a-uuid"}})
        with pytest.raises(HTTPException) as exc:
            require_user(request)
        assert exc.value.status_code == 401
