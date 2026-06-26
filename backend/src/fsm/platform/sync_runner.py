"""Runner for the inbound Google Calendar sync poller.

Provides poll_once (single sweep of all connected technicians) and run_forever
(loop that polls on a configurable interval). The __main__ entry point allows
running the poller as a standalone process:

    python -m fsm.platform.sync_runner
"""
from __future__ import annotations

import logging
import threading

from fsm.calendar.adapters.client_factory import build_calendar_client
from fsm.calendar.adapters.inbound_sync import GoogleCalendarSyncAdapter
from fsm.calendar.adapters.repositories import SqlAlchemyCalendarConnectionRepository
from fsm.calendar.adapters.token_cipher import FernetTokenCipher
from fsm.platform.calendar_errors import is_auth_error
from fsm.platform.notifications_factory import build_notifications
from fsm.scheduling.adapters.unit_of_work import SqlAlchemyUnitOfWork
from fsm.scheduling.application.reconciliation_service import ReconciliationService

_log = logging.getLogger(__name__)


def _mark_disconnected(technician_id, session_factory) -> None:
    """Mark a technician's calendar connection DISCONNECTED after an auth failure.

    Called when list_changes raises an auth error; keeps poll_once from stalling
    other technicians. Projection resumes automatically after the technician
    reconnects via /calendar/connect.
    """
    try:
        with session_factory() as session:
            with session.begin():
                repo = SqlAlchemyCalendarConnectionRepository(session)
                connection = repo.get(technician_id)
                connection.disconnect()
                repo.save(connection)
        _log.warning(
            "Calendar auth error for technician %s during sync — marked DISCONNECTED",
            technician_id,
        )
    except Exception:
        _log.exception(
            "Failed to mark technician %s DISCONNECTED after auth error during sync",
            technician_id,
        )


def poll_once(
    session_factory,
    settings,
    *,
    client_factory=build_calendar_client,
    notifications=None,
) -> int:
    """Poll every CONNECTED technician's FSM calendar and reconcile inbound changes.

    For each connection: decrypts its refresh token, fetches changed events via
    GoogleCalendarSyncAdapter, and reconciles each change via ReconciliationService
    inside a SqlAlchemyUnitOfWork. The new sync token is persisted after the
    reconciliation transaction commits. One failed technician does not stall the others.

    Returns the total number of changes reconciled across all technicians.
    """
    notification_port = notifications
    total = 0

    with session_factory() as session:
        repo = SqlAlchemyCalendarConnectionRepository(session)
        connections = repo.list_connected()

    for connection in connections:
        try:
            total += _process_connection(
                connection,
                session_factory,
                settings,
                client_factory=client_factory,
                caller_notifications=notification_port,
            )
        except Exception as exc:
            if is_auth_error(exc):
                _mark_disconnected(connection.technician_id, session_factory)
            else:
                _log.exception(
                    "Unexpected error syncing technician %s; skipping", connection.technician_id
                )

    return total


def _process_connection(
    connection, session_factory, settings, *, client_factory, caller_notifications
) -> int:
    """Sync a single technician: fetch changes, reconcile, persist token. Return change count."""
    with session_factory() as session:
        repo = SqlAlchemyCalendarConnectionRepository(session)
        encrypted_token = repo.get_encrypted_token(connection.technician_id)
        sync_token = repo.get_sync_token(connection.technician_id)

    token_key = settings.fsm_token_key.get_secret_value()
    refresh_token = FernetTokenCipher(token_key).decrypt(encrypted_token)

    client = client_factory(
        refresh_token=refresh_token,
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret.get_secret_value(),
    )
    sync_adapter = GoogleCalendarSyncAdapter(client, connection.fsm_calendar_id)
    changes, next_sync_token = sync_adapter.list_changes(sync_token)

    with SqlAlchemyUnitOfWork(session_factory) as uow:
        notifications = caller_notifications or build_notifications(uow.session, settings)
        service = ReconciliationService(uow.appointments, uow.outbox, notifications)
        for change in changes:
            service.reconcile(change)
        uow.commit()


    with session_factory() as session:
        with session.begin():
            repo = SqlAlchemyCalendarConnectionRepository(session)
            repo.set_sync_token(connection.technician_id, next_sync_token)

    return len(changes)


def run_forever(session_factory, settings, stop_event: threading.Event) -> None:
    """Poll all connected technicians repeatedly until stop_event is set.

    Each iteration calls poll_once, then waits fsm_sync_interval_seconds before
    the next iteration. Exceptions within an iteration are logged and the loop
    continues. The loop exits cleanly when stop_event is set.
    """
    _log.info("Sync runner starting (interval=%.1fs)", settings.fsm_sync_interval_seconds)
    while not stop_event.is_set():
        try:
            poll_once(session_factory, settings)
        except Exception:
            _log.exception("Unexpected error in sync poll_once; continuing")
        stop_event.wait(settings.fsm_sync_interval_seconds)
    _log.info("Sync runner stopped")


if __name__ == "__main__":
    from fsm.platform.config import get_settings
    from fsm.platform.db import create_engine_from_settings, session_factory
    from fsm.platform.logging import configure_logging

    configure_logging()
    settings = get_settings()
    engine = create_engine_from_settings(settings)
    factory = session_factory(engine)
    stop = threading.Event()
    try:
        run_forever(factory, settings, stop)
    except KeyboardInterrupt:
        stop.set()
