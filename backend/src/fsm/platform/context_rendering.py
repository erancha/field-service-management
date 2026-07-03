"""Required-field render rule shared by the surface-aware appointment-context resolvers.

A field marked required on a rendering surface must never be silently dropped: when its value is
absent, the resolver substitutes a visible placeholder and logs a warning so the gap surfaces on
the event/notification and in the logs. Renderers keep their plain `if value:` shape — a required
field is therefore always present once passed through this rule.

Lives in the composition root because it is invoked by both the notifications resolver and the
calendar-projection resolver, which cannot share code across their bounded contexts.
"""
from __future__ import annotations

import logging

_log = logging.getLogger(__name__)


def required_field(value: str | None, label: str) -> str:
    """Return the trimmed value, or a "[<label> missing]" placeholder (logged as a warning).

    label is the human-readable field name shown in the placeholder and the warning
    (e.g. "technician phone").
    """
    trimmed = (value or "").strip()
    if trimmed:
        return trimmed
    _log.warning("Required appointment-context field missing: %s", label)
    return f"[{label} missing]"
