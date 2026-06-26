"""Tests for ServiceCallService application use cases."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest

from fsm.scheduling.application import ServiceCallService
from fsm.scheduling.domain import ServiceCallStatus
from tests.scheduling.fakes import InMemoryServiceCallRepository

_FIXED_NOW = datetime(2024, 6, 10, 9, 0, tzinfo=timezone.utc)
_FIXED_ID = UUID("aaaaaaaa-0000-0000-0000-000000000001")


@pytest.fixture
def repo() -> InMemoryServiceCallRepository:
    return InMemoryServiceCallRepository()


@pytest.fixture
def svc(repo: InMemoryServiceCallRepository) -> ServiceCallService:
    return ServiceCallService(
        service_calls=repo,
        clock=lambda: _FIXED_NOW,
        new_id=lambda: _FIXED_ID,
    )


class TestOpenServiceCall:
    def test_returns_service_call_with_given_fields(self, svc: ServiceCallService):
        customer_id = UUID("cccccccc-0000-0000-0000-000000000001")
        sc = svc.open_service_call(
            customer_id=customer_id,
            description="Boiler not working",
            category="plumbing",
        )
        assert sc.customer_id == customer_id
        assert sc.description == "Boiler not working"
        assert sc.category == "plumbing"

    def test_new_service_call_is_open(self, svc: ServiceCallService):
        sc = svc.open_service_call(
            customer_id=UUID("cccccccc-0000-0000-0000-000000000002"),
            description="AC repair",
            category="hvac",
        )
        assert sc.status == ServiceCallStatus.OPEN

    def test_created_at_comes_from_clock(self, svc: ServiceCallService):
        sc = svc.open_service_call(
            customer_id=UUID("cccccccc-0000-0000-0000-000000000003"),
            description="Leak",
            category="plumbing",
        )
        assert sc.created_at == _FIXED_NOW

    def test_id_comes_from_new_id(self, svc: ServiceCallService):
        sc = svc.open_service_call(
            customer_id=UUID("cccccccc-0000-0000-0000-000000000004"),
            description="Leak",
            category="plumbing",
        )
        assert sc.id == _FIXED_ID

    def test_persists_service_call_in_repository(
        self, svc: ServiceCallService, repo: InMemoryServiceCallRepository
    ):
        customer_id = UUID("cccccccc-0000-0000-0000-000000000005")
        sc = svc.open_service_call(
            customer_id=customer_id,
            description="Broken pipe",
            category="plumbing",
        )
        stored = repo.get(sc.id)
        assert stored is sc
