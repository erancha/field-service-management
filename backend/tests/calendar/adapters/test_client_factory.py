"""Tests for build_calendar_client factory.

Patches the googleapiclient discovery.build symbol at its import-site to avoid
any network calls. Asserts that the Credentials object is constructed with the
correct parameters and that the return type wraps the stub service.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from fsm.calendar.adapters.client import GoogleApiCalendarClient
from fsm.calendar.adapters.client_factory import build_calendar_client


def test_build_calendar_client_returns_google_api_client_wrapping_stub_service():
    stub_service = MagicMock()

    with patch("fsm.calendar.adapters.client_factory.build") as mock_build:
        mock_build.return_value = stub_service
        client = build_calendar_client(
            refresh_token="rt-abc123",
            client_id="cid",
            client_secret="csecret",
        )

    assert isinstance(client, GoogleApiCalendarClient)
    # The returned client wraps the stub service
    assert client._service is stub_service


def test_build_calendar_client_passes_correct_credentials_to_discovery_build():
    stub_service = MagicMock()

    with patch("fsm.calendar.adapters.client_factory.build") as mock_build:
        mock_build.return_value = stub_service
        with patch("fsm.calendar.adapters.client_factory.Credentials") as mock_creds_cls:
            mock_creds_instance = MagicMock()
            mock_creds_cls.return_value = mock_creds_instance
            build_calendar_client(
                refresh_token="rt-abc123",
                client_id="cid",
                client_secret="csecret",
                token_uri="https://oauth2.googleapis.com/token",
                scopes=("https://www.googleapis.com/auth/calendar",),
            )

    mock_creds_cls.assert_called_once_with(
        token=None,
        refresh_token="rt-abc123",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="cid",
        client_secret="csecret",
        scopes=["https://www.googleapis.com/auth/calendar"],
    )
    mock_build.assert_called_once_with(
        "calendar", "v3", credentials=mock_creds_instance, cache_discovery=False
    )


def test_build_calendar_client_defaults_to_narrow_scopes():
    """The default credential scopes confine the client to app-created calendars and free/busy.

    Without an explicit scopes override the factory must request only calendar.app.created and
    calendar.freebusy, never the broad .../auth/calendar scope, so a refresh token minted for this
    client can never read or modify the technician's other calendars.
    """
    with patch("fsm.calendar.adapters.client_factory.build") as mock_build:
        mock_build.return_value = MagicMock()
        with patch("fsm.calendar.adapters.client_factory.Credentials") as mock_creds_cls:
            build_calendar_client(
                refresh_token="rt-abc123",
                client_id="cid",
                client_secret="csecret",
            )

    _, kwargs = mock_creds_cls.call_args
    assert kwargs["scopes"] == [
        "https://www.googleapis.com/auth/calendar.app.created",
        "https://www.googleapis.com/auth/calendar.freebusy",
    ]
