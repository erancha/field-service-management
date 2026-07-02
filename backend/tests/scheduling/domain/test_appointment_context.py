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


class TestProblemSummary:
    def test_returns_first_line(self) -> None:
        ctx = AppointmentContext(problem_description="No hot water\nSecond line")
        assert ctx.problem_summary() == "No hot water"

    def test_truncates_long_first_line_with_ellipsis(self) -> None:
        ctx = AppointmentContext(problem_description="x" * 100)
        summary = ctx.problem_summary()
        assert len(summary) == 60
        assert summary.endswith("…")

    def test_blank_problem_yields_empty_string(self) -> None:
        assert AppointmentContext(problem_description="   \n ").problem_summary() == ""
        assert AppointmentContext().problem_summary() == ""


class TestSummaryLine:
    def test_combines_name_and_problem(self) -> None:
        ctx = AppointmentContext(customer_name="Ada Lovelace", problem_description="No hot water")
        assert ctx.summary_line() == "Ada Lovelace — No hot water"

    def test_name_alone_when_no_problem(self) -> None:
        assert AppointmentContext(customer_name="Ada").summary_line() == "Ada"

    def test_problem_alone_when_no_name(self) -> None:
        assert AppointmentContext(problem_description="No hot water").summary_line() == "No hot water"

    def test_generic_fallback_when_empty(self) -> None:
        assert AppointmentContext().summary_line() == "Field service appointment"

    def test_whitespace_only_parts_are_treated_as_absent(self) -> None:
        ctx = AppointmentContext(customer_name="  ", problem_description=" \n ")
        assert ctx.summary_line() == "Field service appointment"
