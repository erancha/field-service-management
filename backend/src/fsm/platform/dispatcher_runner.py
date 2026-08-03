"""Runner for the calendar projection dispatcher.

Provides build_dispatcher (composes UoW + resolver into a CalendarProjectionDispatcher) and
run_forever (loop that drains the outbox on a configurable interval). Several of these may run at
once against one database, unlike the inbound sync poller: the outbox is claimed with
SELECT ... FOR UPDATE SKIP LOCKED, so concurrent dispatchers partition entries between them, and
the deterministic iCalUID makes a lost race idempotent at Google.
"""
from __future__ import annotations

import logging
import threading
from typing import Callable
from uuid import UUID

from fsm.google_calendar.adapters.repositories import SqlAlchemyCalendarConnectionRepository
from fsm.platform.calendar_errors import is_auth_error
from fsm.platform.calendar_resolver import build_calendar_resolver
from fsm.platform.context_rendering import required_field
from fsm.platform.identity_lookup import load_user
from fsm.scheduling.adapters.unit_of_work import SqlAlchemyUnitOfWork
from fsm.scheduling.application.calendar_projection_dispatcher import CalendarProjectionDispatcher
from fsm.scheduling.domain.appointment_context import AppointmentContext

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


def _load_user_via_factory(session_factory, user_id: UUID):
    """Open a short session and load a user, degrading to None (logged) on any failure.

    Shared by the customer and technician context resolvers so the dispatcher stays free of a
    direct identity-context import; the identity lookup lives here in the composition root.
    """
    try:
        with session_factory() as session:
            return load_user(session, user_id)
    except Exception:
        _log.exception("Session for context lookup failed; user_id=%s", user_id)
        return None


def build_customer_context_resolver(session_factory) -> Callable[[UUID], AppointmentContext]:
    """Return a callable resolving a customer id to their profile context (preferred name,
    address, phone) for the technician's calendar event.

    customer_name, service_address (the event location), and customer_phone are required on the
    technician's event: a missing value renders as a visible placeholder plus a warning rather than
    dropping silently.
    """

    def _resolve(customer_id: UUID) -> AppointmentContext:
        user = _load_user_via_factory(session_factory, customer_id)
        return AppointmentContext(
            customer_name=required_field(user.preferred_name if user else None, "customer name"),
            service_address=required_field(user.address if user else None, "service address"),
            customer_phone=required_field(user.phone if user else None, "customer phone"),
        )

    return _resolve


def build_technician_context_resolver(session_factory) -> Callable[[UUID], AppointmentContext]:
    """Return a callable resolving a technician id to a context carrying their name and phone.

    The technician's own event echoes the contact the customer was given (the same name and phone
    the notification carries), so the technician can confirm it is correct. Both are required on
    that surface: a missing value renders as a visible placeholder plus a warning.
    """

    def _resolve(technician_id: UUID) -> AppointmentContext:
        user = _load_user_via_factory(session_factory, technician_id)
        return AppointmentContext(
            technician_name=required_field(user.preferred_name if user else None, "technician name"),
            technician_phone=required_field(user.phone if user else None, "technician phone"),
        )

    return _resolve


def photo_url_builder(base_url: str) -> Callable[[UUID, UUID], str]:
    """Return a callable forming the absolute photo-download URL under the given public base.

    The path mirrors the scheduling API's download route, so the link lands on the same
    participant-checked endpoint the web app uses.
    """
    base = base_url.rstrip("/")

    def _url(service_call_id: UUID, photo_id: UUID) -> str:
        return f"{base}/api/service-calls/{service_call_id}/photos/{photo_id}"

    return _url


def require_technician_app_url(settings) -> str:
    """Return the technician deployment's public base URL, refusing to proceed without it.

    The events the dispatcher writes carry photo links built from this URL; emitting events
    silently without them would hide a misconfigured deployment, so a dispatch-enabled process
    must fail at startup instead.
    """
    if settings.technician_app_url is None:
        raise ValueError(
            "technician_app_url is not configured; the calendar dispatcher needs the "
            "technician deployment's public base URL to build photo links"
        )
    return settings.technician_app_url


def build_dispatcher(session_factory, settings) -> CalendarProjectionDispatcher:
    """Compose a CalendarProjectionDispatcher wired to the real DB and calendar resolver."""
    photo_url = photo_url_builder(require_technician_app_url(settings))

    def uow_factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory)

    calendar_resolver = build_calendar_resolver(session_factory, settings)
    on_calendar_error = make_auth_disconnect_handler(session_factory, settings)
    customer_context_resolver = build_customer_context_resolver(session_factory)
    technician_context_resolver = build_technician_context_resolver(session_factory)
    return CalendarProjectionDispatcher(
        uow_factory=uow_factory,
        calendar_resolver=calendar_resolver,
        on_calendar_error=on_calendar_error,
        customer_context_resolver=customer_context_resolver,
        technician_context_resolver=technician_context_resolver,
        photo_url=photo_url,
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
