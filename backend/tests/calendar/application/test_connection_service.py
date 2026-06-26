"""Unit tests for CalendarConnectionService using fakes."""
from __future__ import annotations

import uuid

import pytest

from fsm.calendar.application.connection_service import CalendarConnectionService
from fsm.calendar.domain.connection import CalendarConnection, CalendarConnectionStatus
from fsm.calendar.domain.errors import NotFoundError


class FakeCalendarConnectionRepository:
    def __init__(self):
        self._connections: dict[uuid.UUID, CalendarConnection] = {}
        self._tokens: dict[uuid.UUID, str] = {}

    def add(self, connection: CalendarConnection, encrypted_refresh_token: str) -> None:
        self._connections[connection.technician_id] = connection
        self._tokens[connection.technician_id] = encrypted_refresh_token

    def get(self, technician_id: uuid.UUID) -> CalendarConnection:
        if technician_id not in self._connections:
            raise NotFoundError(f"No connection for {technician_id}")
        return self._connections[technician_id]

    def get_encrypted_token(self, technician_id: uuid.UUID) -> str:
        if technician_id not in self._tokens:
            raise NotFoundError(f"No token for {technician_id}")
        return self._tokens[technician_id]

    def save(self, connection: CalendarConnection) -> None:
        if connection.technician_id not in self._connections:
            raise NotFoundError(f"No connection for {connection.technician_id}")
        self._connections[connection.technician_id] = connection


class FakeTokenCipher:
    """Reversible fake: prefix with 'enc:' to distinguish from plaintext."""

    def encrypt(self, plaintext: str) -> str:
        return f"enc:{plaintext}"

    def decrypt(self, token: str) -> str:
        return token.removeprefix("enc:")


class FakeGoogleCalendarClient:
    CANNED_CALENDAR_ID = "fake-calendar-id-001"

    def create_calendar(self, summary: str) -> str:
        return self.CANNED_CALENDAR_ID

    def insert_event(self, calendar_id, body): ...
    def update_event(self, calendar_id, event_id, body): ...
    def delete_event(self, calendar_id, event_id): ...
    def query_busy(self, calendar_id, time_min, time_max): return []


class TestCalendarConnectionService:
    def _make_service(self):
        repo = FakeCalendarConnectionRepository()
        cipher = FakeTokenCipher()
        client = FakeGoogleCalendarClient()
        svc = CalendarConnectionService(repo=repo, cipher=cipher, client=client)
        return svc, repo, cipher, client

    def test_connect_provisions_calendar_and_persists_connection(self):
        svc, repo, cipher, client = self._make_service()
        tech_id = uuid.uuid4()
        token = "real-refresh-token"

        connection = svc.connect(tech_id, token)

        assert connection.technician_id == tech_id
        assert connection.fsm_calendar_id == FakeGoogleCalendarClient.CANNED_CALENDAR_ID
        assert connection.status == CalendarConnectionStatus.CONNECTED

    def test_connect_stores_encrypted_token_not_plaintext(self):
        svc, repo, cipher, client = self._make_service()
        tech_id = uuid.uuid4()
        plaintext = "real-refresh-token"

        svc.connect(tech_id, plaintext)

        stored = repo.get_encrypted_token(tech_id)
        assert stored != plaintext
        assert stored == cipher.encrypt(plaintext)

    def test_connect_stored_blob_is_the_ciphertext_not_plaintext(self):
        svc, repo, cipher, client = self._make_service()
        tech_id = uuid.uuid4()
        plaintext = "super-secret-token"

        svc.connect(tech_id, plaintext)

        stored_blob = repo.get_encrypted_token(tech_id)
        assert stored_blob == cipher.encrypt(plaintext)
        assert stored_blob != plaintext

    def test_disconnect_flips_status_to_disconnected(self):
        svc, repo, cipher, client = self._make_service()
        tech_id = uuid.uuid4()
        svc.connect(tech_id, "some-token")

        connection = svc.disconnect(tech_id)

        assert connection.status == CalendarConnectionStatus.DISCONNECTED
        persisted = repo.get(tech_id)
        assert persisted.status == CalendarConnectionStatus.DISCONNECTED
