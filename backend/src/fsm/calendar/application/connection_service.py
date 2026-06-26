"""CalendarConnectionService: connect and disconnect technician calendar integrations.

Orchestrates calendar provisioning, token encryption, and connection persistence.
Never logs or returns plaintext refresh tokens.
"""
from __future__ import annotations

import uuid

from fsm.calendar.adapters.client import GoogleCalendarClient
from fsm.calendar.domain.connection import CalendarConnection, CalendarConnectionStatus
from fsm.calendar.ports.repositories import CalendarConnectionRepository
from fsm.calendar.ports.token_cipher import TokenCipher


class CalendarConnectionService:
    """Application service for technician calendar connection lifecycle.

    Core responsibilities:
    - connect: provision a dedicated FSM calendar, encrypt the refresh token, persist the connection
    - disconnect: load the connection, mark it disconnected, persist
    """

    def __init__(
        self,
        repo: CalendarConnectionRepository,
        cipher: TokenCipher,
        client: GoogleCalendarClient,
    ) -> None:
        self._repo = repo
        self._cipher = cipher
        self._client = client

    def connect(self, technician_id: uuid.UUID, refresh_token: str) -> CalendarConnection:
        """Provision a dedicated FSM calendar and store the encrypted refresh token.

        Returns the new CONNECTED CalendarConnection. The plaintext refresh_token
        is never persisted or logged.
        """
        calendar_id = self._client.create_calendar("Field Service")
        encrypted_token = self._cipher.encrypt(refresh_token)
        connection = CalendarConnection(
            technician_id=technician_id,
            fsm_calendar_id=calendar_id,
            status=CalendarConnectionStatus.CONNECTED,
        )
        self._repo.add(connection, encrypted_token)
        return connection

    def disconnect(self, technician_id: uuid.UUID) -> CalendarConnection:
        """Mark the technician's calendar connection as DISCONNECTED."""
        connection = self._repo.get(technician_id)
        connection.disconnect()
        self._repo.save(connection)
        return connection
