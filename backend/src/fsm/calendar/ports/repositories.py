"""CalendarConnectionRepository port: outbound seam for connection persistence."""
from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable

from fsm.calendar.domain.connection import CalendarConnection


@runtime_checkable
class CalendarConnectionRepository(Protocol):
    """Persistence contract for CalendarConnection entities.

    The encrypted_refresh_token is stored alongside the connection but never
    on the domain entity itself. Callers retrieve it separately and decrypt
    it via TokenCipher when a live credential is needed.
    """

    def add(self, connection: CalendarConnection, encrypted_refresh_token: str) -> None:
        """Persist a new connection and its encrypted token.

        Raises DuplicateTechnicianError if a connection for technician_id already exists.
        """
        ...

    def get(self, technician_id: uuid.UUID) -> CalendarConnection:
        """Return the connection for the given technician.

        Raises NotFoundError if absent.
        """
        ...

    def get_encrypted_token(self, technician_id: uuid.UUID) -> str:
        """Return the stored encrypted token blob for the given technician.

        Raises NotFoundError if absent.
        """
        ...

    def save(self, connection: CalendarConnection) -> None:
        """Persist mutations to an already-stored connection.

        Raises NotFoundError if the technician has no existing connection.
        """
        ...

    def get_sync_token(self, technician_id: uuid.UUID) -> str | None:
        """Return the stored Google Calendar sync token for the given technician.

        Raises NotFoundError if absent.
        """
        ...

    def set_sync_token(self, technician_id: uuid.UUID, token: str | None) -> None:
        """Persist an updated sync token for the given technician.

        Raises NotFoundError if absent.
        """
        ...

    def list_connected(self) -> list[CalendarConnection]:
        """Return all connections whose status is CONNECTED."""
        ...
