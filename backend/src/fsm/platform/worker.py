"""Composition root for the worker deployment: the calendar loops and the leadership they need.

The deployment serves no HTTP. It runs the outbound projection dispatcher, which is safe to run
concurrently, and the inbound sync poller, which is not: two pollers would read the same Google
sync token and reconcile the same changes twice. A lease keeps the poller to one holder, and a
process that loses it stands by rather than exiting, so running this deployment at more than one
replica gives a warm standby that takes over when the holder dies.

    python -m fsm.platform.worker
"""
from __future__ import annotations

import asyncio
import logging
import signal
import threading
from functools import partial

from fsm.core.lease import Lease, PostgresAdvisoryLease
from fsm.platform.events import publish_appointment_changed_on
from fsm.platform.roles import DEPLOYMENTS, Worker

_log = logging.getLogger(__name__)

WORKER_ROLE = "worker"

# Fixed 63-bit advisory-lock key naming the inbound-sync hold ("fsm_sync" in ASCII). Any process
# competing for the poller must use this exact value, so it lives here rather than at a call site.
SYNC_LEASE_KEY = 0x66736D5F73796E63


def run_sync_under_lease(
    lease: Lease, poll_loop, stop_event: threading.Event, retry_seconds: float
) -> None:
    """Run poll_loop only while this process holds lease, standing by while another holds it.

    poll_loop is expected to return once stop_event is set. A process that fails to take the lease
    waits retry_seconds and tries again, so the poller resumes on another replica after the holder
    disconnects without anyone intervening.
    """
    while not stop_event.is_set():
        if lease.acquire():
            _log.info("Inbound sync lease acquired; polling")
            try:
                poll_loop()
            finally:
                lease.release()
        else:
            _log.info("Inbound sync lease held elsewhere; standing by")
            stop_event.wait(retry_seconds)


def _start_calendar_dispatch(session_factory, settings, stop_event, publish) -> threading.Thread:
    """Start the loop draining the calendar outbox to Google, in a daemon thread."""
    from fsm.platform.dispatcher_runner import require_technician_app_url, run_forever

    # Checked before the thread spawns: a raise inside it would leave the worker running with one
    # loop missing and nothing reporting why.
    require_technician_app_url(settings)

    thread = threading.Thread(
        target=run_forever,
        args=(session_factory, settings, stop_event),
        daemon=True,
        name=Worker.CALENDAR_DISPATCH.value,
    )
    thread.start()
    return thread


def _start_inbound_sync(session_factory, settings, stop_event, publish) -> threading.Thread:
    """Start the Google-polling loop under the single-holder lease, in a daemon thread."""
    from fsm.platform.sync_runner import run_forever

    lease = PostgresAdvisoryLease(session_factory, SYNC_LEASE_KEY)
    poll_loop = partial(run_forever, session_factory, settings, stop_event, publish)

    thread = threading.Thread(
        target=run_sync_under_lease,
        args=(lease, poll_loop, stop_event, settings.fsm_sync_lease_retry_seconds),
        daemon=True,
        name=Worker.INBOUND_SYNC.value,
    )
    thread.start()
    return thread


# Starters share one signature, so a process is composed by walking its deployment's worker list
# rather than by knowing what any individual loop needs.
_START_WORKER = {
    Worker.CALENDAR_DISPATCH: _start_calendar_dispatch,
    Worker.INBOUND_SYNC: _start_inbound_sync,
}


def start_workers(session_factory, settings, stop_event, publish) -> list[threading.Thread]:
    """Start every loop the worker deployment declares in roles.py, returning their threads."""
    return [
        _START_WORKER[worker](session_factory, settings, stop_event, publish)
        for worker in DEPLOYMENTS[WORKER_ROLE].workers
    ]


def _build_publisher(settings):
    """Return a publish callback for inbound changes, and the loop its publishes run on.

    The worker has no serving loop to borrow, so it runs one of its own on a daemon thread: the
    Redis client is async and its connections belong to the loop that opened them, which rules out
    a fresh loop per publish. Both are None where no broker is configured, since an in-process bus
    reaches no stream outside this process and the changes have nowhere to go.
    """
    if not settings.redis_url:
        _log.warning("REDIS_URL unset; inbound calendar changes will not reach live streams")
        return None, None

    from fsm.core.events import build_event_bus

    bus = build_event_bus(settings.redis_url)
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, name="fsm-worker-events", daemon=True)
    thread.start()

    def publish(change) -> None:
        publish_appointment_changed_on(
            loop,
            bus,
            appointment_id=change.appointment_id,
            customer_id=change.customer_id,
            technician_id=change.technician_id,
        )

    return publish, loop


def main() -> None:
    """Run the worker deployment until the process is asked to stop."""
    from fsm.core.db import session_factory
    from fsm.platform.config import get_settings
    from fsm.platform.db import create_engine_from_settings
    from fsm.platform.logging import configure_logging

    configure_logging()
    settings = get_settings()
    factory = session_factory(create_engine_from_settings(settings))

    stop_event = threading.Event()
    publish, event_loop = _build_publisher(settings)
    threads = start_workers(factory, settings, stop_event, publish)
    _log.info("Worker started: %s", ", ".join(thread.name for thread in threads))

    # SIGTERM is how a container stop arrives; handling it lets the lease be released on the way
    # out instead of waiting for the database to notice a dropped connection.
    signal.signal(signal.SIGTERM, lambda *_: stop_event.set())
    try:
        while not stop_event.wait(1.0):
            pass
    except KeyboardInterrupt:
        stop_event.set()
    finally:
        for thread in threads:
            thread.join(timeout=5.0)
        if event_loop is not None:
            event_loop.call_soon_threadsafe(event_loop.stop)
    _log.info("Worker stopped")


if __name__ == "__main__":
    main()
