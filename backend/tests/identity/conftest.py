"""Pytest fixtures exposing in-memory fake implementations of identity ports."""
from __future__ import annotations

import pytest

from tests.identity.fakes import FakeAuthPort, InMemoryUserRepository


@pytest.fixture
def user_repo() -> InMemoryUserRepository:
    return InMemoryUserRepository()


@pytest.fixture
def fake_auth() -> FakeAuthPort:
    return FakeAuthPort()
