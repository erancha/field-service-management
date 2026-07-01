"""Unit tests for the AppointmentContext value object."""
from __future__ import annotations

import dataclasses

import pytest

from fsm.scheduling.domain.appointment_context import AppointmentContext


def test_holds_customer_name_and_problem() -> None:
    ctx = AppointmentContext(customer_name="Ada Lovelace", problem_description="No hot water")
    assert ctx.customer_name == "Ada Lovelace"
    assert ctx.problem_description == "No hot water"


def test_fields_default_to_none() -> None:
    ctx = AppointmentContext()
    assert ctx.customer_name is None
    assert ctx.problem_description is None


def test_is_frozen() -> None:
    ctx = AppointmentContext(customer_name="Ada")
    with pytest.raises(dataclasses.FrozenInstanceError):
        ctx.customer_name = "Grace"  # type: ignore[misc]
