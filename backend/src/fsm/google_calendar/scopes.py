"""OAuth scopes granted for the technician Google Calendar integration.

Enforces the privacy-by-construction model: calendar.app.created confines the app to calendars it
itself created, so the technician's private calendar is invisible to the system; calendar.freebusy
returns only opaque busy/free intervals, never titles or attendees. The broad .../auth/calendar
scope is deliberately never requested — isolation, not operation-restriction, is what keeps private
events private.
"""
from __future__ import annotations

CALENDAR_OAUTH_SCOPES = (
    "https://www.googleapis.com/auth/calendar.app.created",
    "https://www.googleapis.com/auth/calendar.freebusy",
)
