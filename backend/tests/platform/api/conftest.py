"""Shared fixtures for the API integration tests.

The scheduling API is gated by require_user; tests authenticate by overriding that
dependency on the app under test rather than minting real signed-session cookies.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from fsm.identity.domain.role import Role
from fsm.identity.domain.role_status import RoleStatus
from fsm.platform.api.auth_deps import SessionUser, require_user


@pytest.fixture(autouse=True)
def _freeze_availability_now(monkeypatch):
    """Freeze the availability endpoint's clock so slot assertions on fixed historical
    dates are not emptied by the past-slot filter.

    The availability endpoint excludes slots that begin before now. These integration
    tests request availability for fixed dates (some pinned for DST/timezone determinism)
    that are in the past relative to the real clock, so without a frozen clock every
    slot would be filtered out. Anchoring now well before those dates keeps the
    endpoint's other behaviour (working hours, holidays, days off, free/busy) under test.
    Tests that assert the past-filter itself override this with their own value.
    """
    monkeypatch.setattr(
        "fsm.platform.api.scheduling_routes._now_utc",
        lambda: datetime(2020, 1, 1, tzinfo=timezone.utc),
    )


@pytest.fixture
def authenticate():
    """Stamp a session user on a FastAPI app by overriding require_user.

    `authenticate(app, user_id=None, role=Role.CUSTOMER, role_status=RoleStatus.APPROVED) -> UUID`
    — pass `client.app` for TestClient-based tests, or the inline `app` for tests that build their
    own. Returns the stamped user id; overrides are cleared after the test so the default request
    is gated. role_status defaults to APPROVED so existing tests describe an effective user.
    """
    patched = []

    def _set(
        app,
        user_id: uuid.UUID | None = None,
        role: Role = Role.CUSTOMER,
        role_status: RoleStatus = RoleStatus.APPROVED,
    ) -> uuid.UUID:
        uid = user_id if user_id is not None else uuid.uuid4()
        app.dependency_overrides[require_user] = lambda: SessionUser(
            id=uid, role=role, email="user@example.com", role_status=role_status
        )
        patched.append(app)
        return uid

    yield _set
    for app in patched:
        app.dependency_overrides.pop(require_user, None)
