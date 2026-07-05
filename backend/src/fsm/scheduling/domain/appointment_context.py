"""Transient enrichment data for rendering an appointment into a calendar event or notification.

Assembled per projection from the service call and the parties' profiles; never persisted.
Fields are optional at the type level because each surface's resolver populates only what that
surface renders; a field the surface requires arrives as a visible "[<label> missing]"
placeholder (with a logged warning) rather than None, so renderers may treat required fields
as always present. Calendar renderers additionally tolerate bare contexts from projections
configured without a resolver; the notification renderer treats a blank required field as a
wiring bug and raises.
"""
from __future__ import annotations

from dataclasses import dataclass

_TITLE_PROBLEM_LIMIT = 60
_GENERIC_TITLE = "Field service appointment"


@dataclass(frozen=True)
class AppointmentContext:
    """Immutable bundle of appointment context not present on the Appointment entity.

    customer_name is the display name to show for the customer; problem_description is the
    service call's reported problem. Both are optional and default to None.
    service_address and customer_phone come from the customer's profile; renderers place them in
    the event location and contact lines.
    technician_name and technician_phone identify the assigned technician; the notifications
    resolver populates them for the customer, and the dispatcher resolver populates them for the
    technician's own event so the technician can confirm the contact the customer was given.

    Title composition lives here so the Google event title and the ICS SUMMARY render
    identically and the email subject leads with the same problem summary. Notification
    application code calls these methods duck-typed: the import contracts bar
    fsm.notifications.application from importing fsm.scheduling.
    """

    customer_name: str | None = None
    problem_description: str | None = None
    service_address: str | None = None
    customer_phone: str | None = None
    technician_name: str | None = None
    technician_phone: str | None = None

    def problem_summary(self) -> str:
        """First line of the problem, truncated to the title limit; '' when absent or blank."""
        stripped = (self.problem_description or "").strip()
        if not stripped:
            return ""
        first_line = stripped.splitlines()[0]
        if len(first_line) <= _TITLE_PROBLEM_LIMIT:
            return first_line
        return first_line[: _TITLE_PROBLEM_LIMIT - 1].rstrip() + "…"

    def summary_line(self) -> str:
        """Compose "{customer} — {short problem}", falling back to whichever part is known,
        then to a generic title when neither is."""
        name = (self.customer_name or "").strip()
        problem = self.problem_summary()
        if name and problem:
            return f"{name} — {problem}"
        return name or problem or _GENERIC_TITLE
