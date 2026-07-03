"""Unit tests for E.164 phone-number validation (the server-side accept/reject gate)."""
from __future__ import annotations

import pytest

from fsm.identity.domain.phone import is_valid_phone


@pytest.mark.parametrize(
    "value",
    [
        "054-7586288",
        "0547586288",
        "(054) 758-6288",
        "+972-54-7586288",
        "+1-202-555-0143",  # non-Israeli, still a valid E.164 number
        "055-12345678",  # 11 digits — allowed, though not a valid Israeli mobile
        "03-1234567",
    ],
)
def test_accepts_e164_shaped_numbers(value: str) -> None:
    assert is_valid_phone(value) is True


@pytest.mark.parametrize(
    "value",
    [
        "12345",  # 5 digits — too short
        "0123456789012345",  # 16 digits — exceeds E.164
        "",
        "   ",
        "call me",
        "054-758-628a",
        "054/7586288",
    ],
)
def test_rejects_non_e164(value: str) -> None:
    assert is_valid_phone(value) is False
