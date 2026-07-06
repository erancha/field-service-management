"""Google Calendar integration context: connections, the raw API client, free/busy, and sync.

Owns the technician's Google connection lifecycle and the GoogleCalendarClient port; the abstract
calendar seam consumed by scheduling is scheduling.ports.CalendarPort, not this package.
"""
