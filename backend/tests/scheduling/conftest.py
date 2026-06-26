"""Pytest fixtures exposing in-memory fake implementations of scheduling ports."""
from __future__ import annotations

import pytest

from tests.scheduling.fakes import (
    FakeCalendarPort,
    FakeNotificationPort,
    InMemoryAppointmentRepository,
    InMemoryOutboxRepository,
    InMemoryServiceCallRepository,
)


@pytest.fixture
def service_call_repo() -> InMemoryServiceCallRepository:
    return InMemoryServiceCallRepository()


@pytest.fixture
def appointment_repo() -> InMemoryAppointmentRepository:
    return InMemoryAppointmentRepository()


@pytest.fixture
def fake_calendar() -> FakeCalendarPort:
    return FakeCalendarPort()


@pytest.fixture
def fake_notifications() -> FakeNotificationPort:
    return FakeNotificationPort()


@pytest.fixture
def fake_outbox() -> InMemoryOutboxRepository:
    return InMemoryOutboxRepository()
