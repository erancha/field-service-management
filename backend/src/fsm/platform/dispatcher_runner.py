"""Runner for the calendar projection dispatcher.

Provides build_dispatcher (composes UoW + resolver into a CalendarProjectionDispatcher)
and run_forever (loop that drains the outbox on a configurable interval). The
__main__ entry point allows running the dispatcher as a standalone process:

    python -m fsm.platform.dispatcher_runner
"""
from __future__ import annotations

import logging
import threading
from typing import Callable
from uuid import UUID

from fsm.calendar.adapters.repositories import SqlAlchemyCalendarConnectionRepository
from fsm.platform.calendar_errors import is_auth_error
from fsm.platform.calendar_resolver import build_calendar_resolver
from fsm.scheduling.adapters.unit_of_work import SqlAlchemyUnitOfWork
from fsm.scheduling.application.calendar_projection_dispatcher import CalendarProjectionDispatcher

_log = logging.getLogger(__name__)


def make_auth_disconnect_handler(
    session_factory, settings
) -> Callable[[UUID, Exception], None]:
    """Return a callback that marks a technician's calendar connection DISCONNECTED on auth errors.

    Non-auth errors are ignored; the dispatcher already handles retries for those.
    Projection resumes automatically after the technician reconnects via /calendar/connect.
    """
    def _handler(technician_id: UUID, exc: Exception) -> None:
        if not is_auth_error(exc):
            return
        try:
            with session_factory() as session:
                with session.begin():
                    repo = SqlAlchemyCalendarConnectionRepository(session)
                    connection = repo.get(technician_id)
                    connection.disconnect()
                    repo.save(connection)
            _log.warning(
                "Calendar auth error for technician %s — marked connection DISCONNECTED: %s",
                technician_id,
                exc,
            )
        except Exception:
            _log.exception(
                "Failed to mark technician %s DISCONNECTED after auth error", technician_id
            )

    return _handler


def build_customer_name_resolver(session_factory) -> Callable[[UUID], str | None]:
    """Return a callable resolving a customer user id to their name, or None on any failure.

    Mirrors the notifications recipient_email seam so the scheduling dispatcher stays free of a
    direct identity-context import; the identity lookup lives here in the composition root.
    """

    def _resolve(customer_id: UUID) -> str | None:
        from fsm.identity.adapters.repositories import SqlAlchemyUserRepository

        try:
            with session_factory() as session:
                user = SqlAlchemyUserRepository(session).get(customer_id)
                return user.name
        except Exception:
            return None

    return _resolve


def build_dispatcher(session_factory, settings) -> CalendarProjectionDispatcher:
    """Compose a CalendarProjectionDispatcher wired to the real DB and calendar resolver."""
    uow_factory = lambda: SqlAlchemyUnitOfWork(session_factory)
    calendar_resolver = build_calendar_resolver(session_factory, settings)
    on_calendar_error = make_auth_disconnect_handler(session_factory, settings)
    customer_name_resolver = build_customer_name_resolver(session_factory)
    return CalendarProjectionDispatcher(
        uow_factory=uow_factory,
        calendar_resolver=calendar_resolver,
        on_calendar_error=on_calendar_error,
        customer_name_resolver=customer_name_resolver,
    )


def run_forever(session_factory, settings, stop_event: threading.Event) -> None:
    """Drain the outbox repeatedly until stop_event is set.

    Each iteration calls dispatcher.run_once(), then waits for
    fsm_dispatch_interval_seconds before the next iteration. The loop exits
    cleanly when stop_event is set, which allows the caller to terminate it
    from a shutdown handler.
    """
    _log.info("Dispatcher runner starting (interval=%.1fs)", settings.fsm_dispatch_interval_seconds)
    dispatcher = build_dispatcher(session_factory, settings)
    while not stop_event.is_set():
        try:
            dispatcher.run_once()
        except Exception:
            _log.exception("Unexpected error in dispatcher run_once; continuing")
        stop_event.wait(settings.fsm_dispatch_interval_seconds)
    _log.info("Dispatcher runner stopped")


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
