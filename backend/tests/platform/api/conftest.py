"""Shared fixtures for the API integration tests.

The scheduling API is gated by require_user; tests authenticate by overriding that
dependency on the app under test rather than minting real signed-session cookies.
"""
from __future__ import annotations

import uuid

import pytest

from fsm.identity.domain.role import Role
from fsm.platform.api.auth_deps import SessionUser, require_user


@pytest.fixture
def authenticate():
    """Stamp a session user on a FastAPI app by overriding require_user.

    `authenticate(app, user_id=None, role=Role.CUSTOMER) -> UUID` — pass `client.app` for
    TestClient-based tests, or the inline `app` for tests that build their own. Returns the
    stamped user id; overrides are cleared after the test so the default request is gated.
    """
    patched = []

    def _set(app, user_id: uuid.UUID | None = None, role: Role = Role.CUSTOMER) -> uuid.UUID:
        uid = user_id if user_id is not None else uuid.uuid4()
        app.dependency_overrides[require_user] = lambda: SessionUser(
            id=uid, role=role, email="user@example.com"
        )
        patched.append(app)
        return uid

    yield _set
    for app in patched:
        app.dependency_overrides.pop(require_user, None)
