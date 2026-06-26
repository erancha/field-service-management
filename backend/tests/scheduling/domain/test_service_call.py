"""Tests for ServiceCall entity and ServiceCallStatus enum."""
import uuid
from datetime import datetime, timezone
import pytest

from fsm.scheduling.domain import (
    ServiceCall,
    ServiceCallStatus,
    InvalidTransition,
)


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _new_call(**kwargs) -> ServiceCall:
    defaults = dict(
        id=uuid.uuid4(),
        customer_id=uuid.uuid4(),
        description="Fix HVAC unit",
        category="HVAC",
        status=ServiceCallStatus.OPEN,
        created_at=_now(),
    )
    defaults.update(kwargs)
    return ServiceCall(**defaults)


class TestServiceCallCreation:
    def test_creates_with_open_status(self):
        sc = _new_call()
        assert sc.status == ServiceCallStatus.OPEN

    def test_fields_accessible(self):
        sc_id = uuid.uuid4()
        cust_id = uuid.uuid4()
        sc = _new_call(id=sc_id, customer_id=cust_id, description="Repair AC")
        assert sc.id == sc_id
        assert sc.customer_id == cust_id
        assert sc.description == "Repair AC"


class TestServiceCallTransitions:
    def test_open_to_scheduled_succeeds(self):
        sc = _new_call()
        sc.mark_scheduled()
        assert sc.status == ServiceCallStatus.SCHEDULED

    def test_scheduled_to_scheduled_raises(self):
        sc = _new_call()
        sc.mark_scheduled()
        with pytest.raises(InvalidTransition):
            sc.mark_scheduled()

    def test_cancelled_to_scheduled_raises(self):
        sc = _new_call(status=ServiceCallStatus.CANCELLED)
        with pytest.raises(InvalidTransition):
            sc.mark_scheduled()

    def test_open_status_is_not_terminal(self):
        sc = _new_call()
        sc.mark_scheduled()
        assert sc.status == ServiceCallStatus.SCHEDULED
