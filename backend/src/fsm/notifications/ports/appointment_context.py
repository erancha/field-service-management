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
    substituted with a visible placeholder by the resolver, never blank. Members are
    read-only properties so immutable producers (frozen dataclasses) conform.
    """

    @property
    def customer_name(self) -> str | None: ...

    @property
    def problem_description(self) -> str | None: ...

    @property
    def service_address(self) -> str | None: ...

    @property
    def customer_phone(self) -> str | None: ...

    @property
    def technician_name(self) -> str | None: ...

    @property
    def technician_phone(self) -> str | None: ...

    def problem_summary(self) -> str:
        """First line of the problem, truncated for titles; '' when absent."""
        ...

    def summary_line(self) -> str:
        """One-line event title composed from customer name and problem."""
        ...
