"""Unit tests for the required-field render rule shared by the surface-aware resolvers."""
from __future__ import annotations

import logging

import pytest

from fsm.platform.context_rendering import required_field


def test_returns_trimmed_value_when_present() -> None:
    assert required_field("  Ada Lovelace  ", "customer name") == "Ada Lovelace"


@pytest.mark.parametrize("value", [None, "", "   ", "\n\t"])
def test_missing_value_yields_placeholder_and_warns(value, caplog) -> None:
    with caplog.at_level(logging.WARNING):
        result = required_field(value, "technician phone")

    assert result == "[technician phone missing]"
    assert any(
        "technician phone" in r.getMessage() and r.levelno == logging.WARNING
        for r in caplog.records
    )
