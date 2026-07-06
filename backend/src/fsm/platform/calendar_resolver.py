"""Composition-root factory that builds a per-technician CalendarPort resolver.

The resolver is the bridge between the scheduling dispatcher (which knows only
the CalendarPort protocol) and the concrete Google calendar infrastructure (which
lives in the google_calendar bounded context). It belongs here — in the platform layer —
because only the composition root is allowed to import both contexts.
"""
from __future__ import annotations

from typing import Callable
from uuid import UUID

from fsm.google_calendar.adapters.client_factory import build_calendar_client
from fsm.platform.calendar_bridge.google_calendar import GoogleCalendarAdapter
from fsm.google_calendar.adapters.repositories import SqlAlchemyCalendarConnectionRepository
from fsm.google_calendar.adapters.token_cipher import FernetTokenCipher
from fsm.google_calendar.domain.errors import NotFoundError
from fsm.platform.dev_adapters import NullCalendarPort
from fsm.platform.identity_lookup import build_email_resolver_via_factory
from fsm.scheduling.ports.calendar import CalendarPort


def build_calendar_resolver(
    session_factory,
    settings,
    *,
    client_factory: Callable = build_calendar_client,
) -> Callable[[UUID], CalendarPort]:
    """Return a resolver that maps a technician_id to the appropriate CalendarPort.

    When Google integration is unconfigured (missing google_client_id,
    google_client_secret, or fsm_token_key), returns a resolver that always
    yields NullCalendarPort so the app operates without credentials.

    For configured environments, each call opens a short session, loads the
    technician's CalendarConnection and encrypted token, decrypts it, builds a
    client, and returns a GoogleCalendarAdapter scoped to that technician's
    calendar. A fresh client is built on every call; none is shared across calls.

    The injectable client_factory parameter (default: build_calendar_client)
    allows tests to supply a fake that avoids real Google API calls.
    """
    if not (settings.google_client_id and settings.google_client_secret and settings.fsm_token_key):
        def _null_resolver(_technician_id: UUID) -> CalendarPort:
            return NullCalendarPort()

        return _null_resolver

    attendee_email = build_email_resolver_via_factory(session_factory)

    def _resolver(technician_id: UUID) -> CalendarPort:
        with session_factory() as session:
            repo = SqlAlchemyCalendarConnectionRepository(session)
            try:
                connection = repo.get(technician_id)
                encrypted_token = repo.get_encrypted_token(technician_id)
            except NotFoundError:
                return NullCalendarPort()

        token_key = settings.fsm_token_key.get_secret_value()
        refresh_token = FernetTokenCipher(token_key).decrypt(encrypted_token)

        client = client_factory(
            refresh_token=refresh_token,
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret.get_secret_value(),
        )
        return GoogleCalendarAdapter(
            client, connection.fsm_calendar_id, attendee_email=attendee_email
        )

    return _resolver
