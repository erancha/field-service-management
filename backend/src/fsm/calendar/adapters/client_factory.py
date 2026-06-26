"""Build a GoogleApiCalendarClient from a refresh token and OAuth credentials.

The factory is the only place that touches google.oauth2 and
googleapiclient.discovery; callers receive a GoogleApiCalendarClient and
never depend on those libraries directly.
"""
from __future__ import annotations

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from fsm.calendar.adapters.client import GoogleApiCalendarClient

_CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar"
_DEFAULT_TOKEN_URI = "https://oauth2.googleapis.com/token"


def build_calendar_client(
    *,
    refresh_token: str,
    client_id: str,
    client_secret: str,
    token_uri: str = _DEFAULT_TOKEN_URI,
    scopes: tuple[str, ...] = (_CALENDAR_SCOPE,),
) -> GoogleApiCalendarClient:
    """Construct a GoogleApiCalendarClient authenticated with the given refresh token."""
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=token_uri,
        client_id=client_id,
        client_secret=client_secret,
        scopes=list(scopes),
    )
    service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    return GoogleApiCalendarClient(service)
