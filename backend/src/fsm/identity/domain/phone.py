"""Phone-number validation for the profile-update entry point.

The app serves an international audience, so a stored phone is accepted on E.164 shape alone: an
optional leading "+" and 7-15 digits once separators (spaces, hyphens, parentheses) are removed.
E.164 caps a number at 15 digits; 7 is a pragmatic lower bound that still admits every real number
while rejecting obvious typos. Country-specific plausibility (e.g. an Israeli mobile is 10 digits)
is surfaced to the user as a soft warning on the frontend, not enforced here.
"""
from __future__ import annotations

import re

_SHAPE = re.compile(r"^\+?[\d\s()-]+$")


def is_valid_phone(value: str) -> bool:
    """Return True when value is a well-formed E.164 phone number (7-15 digits)."""
    trimmed = value.strip()
    if not _SHAPE.match(trimmed):
        return False
    digits = re.sub(r"\D", "", trimmed)
    return 7 <= len(digits) <= 15
