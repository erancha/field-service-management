"""CalendarConnectionService: connect and disconnect technician calendar integrations.

Orchestrates calendar provisioning, token encryption, and connection persistence.
Never logs or returns plaintext refresh tokens.
"""
from __future__ import annotations

import uuid

from fsm.calendar.ports.client import GoogleCalendarClient
from fsm.calendar.domain.connection import CalendarConnection, CalendarConnectionStatus
from fsm.calendar.domain.errors import NotFoundError
from fsm.calendar.ports.repositories import CalendarConnectionRepository
from fsm.calendar.ports.token_cipher import TokenCipher


class CalendarConnectionService:
    """Application service for technician calendar connection lifecycle.

    Core responsibilities:
    - connect: upsert a technician's connection — provision a dedicated FSM calendar on first
      connect, or refresh the credential and reactivate an existing (e.g. DISCONNECTED) connection
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
        """Connect or reconnect a technician's calendar, storing the encrypted refresh token.

        On first connect, provisions a dedicated FSM calendar. On reconnect (a row already
        exists, e.g. left DISCONNECTED by a credential revocation), reuses the existing calendar
        so a repeat consent never leaves an orphan calendar on the technician's account, replaces
        the stored credential with the fresh one, and returns the connection to CONNECTED.

        Returns the CONNECTED CalendarConnection. The plaintext refresh_token is never persisted
        or logged.
        """
        encrypted_token = self._cipher.encrypt(refresh_token)
        try:
            connection = self._repo.get(technician_id)
        except NotFoundError:
            calendar_id = self._client.create_calendar("Field Service Management")
            connection = CalendarConnection(
                technician_id=technician_id,
                fsm_calendar_id=calendar_id,
                status=CalendarConnectionStatus.CONNECTED,
            )
            self._repo.add(connection, encrypted_token)
            return connection

        self._repo.reconnect(technician_id, encrypted_token)
        connection.status = CalendarConnectionStatus.CONNECTED
        return connection

    def disconnect(self, technician_id: uuid.UUID) -> CalendarConnection:
        """Mark the technician's calendar connection as DISCONNECTED."""
        connection = self._repo.get(technician_id)
        connection.disconnect()
        self._repo.save(connection)
        return connection
