"""Transient enrichment data for rendering an appointment into a calendar event or notification.

Assembled per projection from the service call and customer identity; never persisted. Fields
are optional because the underlying data may be missing (e.g. a customer who has not set a
profile), in which case renderers fall back to generic text.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AppointmentContext:
    """Immutable bundle of appointment context not present on the Appointment entity.

    customer_name is the display name to show for the customer; problem_description is the
    service call's reported problem. Both are optional and default to None.
    """

    customer_name: str | None = None
    problem_description: str | None = None
