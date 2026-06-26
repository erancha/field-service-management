"""Holiday value object for the scheduling bounded context."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Holiday:
    """An all-day public holiday that blocks slot generation."""

    date: date
    name: str
