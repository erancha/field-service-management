"""Conformance bridge between the scheduling and google_calendar contexts.

Implements scheduling-owned ports (CalendarPort, the inbound change feed) in terms of the
google_calendar context's GoogleCalendarClient port. Lives in platform because it is composition:
the one place allowed to know both contexts, keeping them mutually independent.
"""
from fsm.platform.calendar_bridge.google_calendar import GoogleCalendarAdapter
from fsm.platform.calendar_bridge.inbound_sync import GoogleCalendarSyncAdapter

__all__ = ["GoogleCalendarAdapter", "GoogleCalendarSyncAdapter"]
