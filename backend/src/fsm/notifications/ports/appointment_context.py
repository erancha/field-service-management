"""Structural contract for the appointment enrichment context notifications render.

The concrete value object lives in the scheduling context, which import contracts bar this
package from importing; this Protocol names the fields and composition methods the renderers
rely on so the dependency stays structural rather than nominal.
"""
from __future__ import annotations

from typing import Protocol


class AppointmentContextView(Protocol):
    """Read view of an appointment's enrichment data as consumed by notification renderers.

    Fields are None when absent on the producing surface; required fields arrive already
    substituted with a visible placeholder by the resolver, never blank.
    """

    customer_name: str | None
    problem_description: str | None
    service_address: str | None
    customer_phone: str | None
    technician_name: str | None
    technician_phone: str | None

    def problem_summary(self) -> str:
        """First line of the problem, truncated for titles; '' when absent."""
        ...

    def summary_line(self) -> str:
        """One-line event title composed from customer name and problem."""
        ...
