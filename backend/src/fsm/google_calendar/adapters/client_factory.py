"""Build a GoogleApiCalendarClient from a refresh token and OAuth credentials.

The factory is the only place that touches google.oauth2 and
googleapiclient.discovery; callers receive a GoogleApiCalendarClient and
never depend on those libraries directly.
"""
from __future__ import annotations

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from fsm.google_calendar.adapters.client import GoogleApiCalendarClient
from fsm.google_calendar.scopes import CALENDAR_OAUTH_SCOPES
from fsm.shared.google_oauth import GOOGLE_TOKEN_URI


def build_calendar_client(
    *,
    refresh_token: str,
    client_id: str,
    client_secret: str,
    token_uri: str = GOOGLE_TOKEN_URI,
    scopes: tuple[str, ...] = CALENDAR_OAUTH_SCOPES,
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
