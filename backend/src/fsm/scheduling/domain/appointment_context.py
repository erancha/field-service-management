"""Transient enrichment data for rendering an appointment into a calendar event or notification.

Assembled per projection from the service call and customer identity; never persisted. Fields
are optional because resolvers degrade them to None when a lookup fails, in which case
renderers fall back to generic text.
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

    Title composition lives here so the Google event title and the ICS SUMMARY render
    identically and the email subject leads with the same problem summary. Notification
    application code calls these methods duck-typed: the import contracts bar
    fsm.notifications.application from importing fsm.scheduling.
    """

    customer_name: str | None = None
    problem_description: str | None = None
    service_address: str | None = None
    customer_phone: str | None = None

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
