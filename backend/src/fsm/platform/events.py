"""FSM's event channels, who may subscribe to them, and the cues published onto them.

Two channel shapes exist: `user:{id}` (delivered only to that user's streams) and `admins`
(delivered to every connected back-office stream). Channel membership is the authorization
boundary — a stream only ever receives events for channels its caller may subscribe to (see
subscribable_channels).

Both the Docker and host deployments run one process per role (customer/technician/back-office)
plus a worker process, so an appointment change raised in one has to reach streams held open in
another: those deployments configure REDIS_URL and get the cross-process bus. Most publish helpers
here reach the bus and the serving loop through app.state, which ties them to the running
application rather than to the transport in fsm.core.events. A process holding no application
supplies a bus and loop of its own instead.
"""
from __future__ import annotations

import asyncio
import logging

from fsm.identity.domain.role import Role
from fsm.identity.domain.role_status import RoleStatus
from fsm.platform.api.auth_deps import SessionUser

_log = logging.getLogger(__name__)

APPOINTMENT_CHANGED = "appointment.changed"
KB_INGEST_PROGRESS = "kb.ingest.progress"

ADMINS_CHANNEL = "admins"


def user_channel(user_id) -> str:
    """Channel carrying events addressed to a single user."""
    return f"user:{user_id}"


def subscribable_channels(user: SessionUser) -> set[str]:
    """Channels a stream opened for this caller may subscribe to, and no others.

    Every caller listens on their own user channel; only an APPROVED administrator additionally
    listens on the back-office channel, so a customer stream can never receive admins events.
    """
    channels = {user_channel(user.id)}
    if user.role is Role.ADMIN and user.role_status is RoleStatus.APPROVED:
        channels.add(ADMINS_CHANNEL)
    return channels


async def _publish(bus, channel: str, event: dict) -> None:
    """Publish to the given bus; a no-op when none is wired (e.g. some tests)."""
    if bus is not None:
        await bus.publish(channel, event)


async def publish_to_app(app, channel: str, event: dict) -> None:
    """Publish to the app's configured event bus; a no-op when none is wired (e.g. some tests)."""
    await _publish(getattr(app.state, "event_bus", None), channel, event)


def _log_publish_failure(event_type: str):
    """Build a done-callback logging a failed publish; SSE cues are best-effort, never raised."""

    def _callback(future) -> None:
        if future.cancelled():
            return
        exc = future.exception()
        if exc is not None:
            _log.warning("%s publish failed: %s", event_type, exc)

    return _callback


def _schedule(loop, bus, channels, event) -> None:
    """Publish event to each channel from any thread, without ever raising at the call site.

    The async publish is scheduled onto the given loop, so a sync route handler or a worker thread
    can raise a cue without awaiting one. A cue arriving before the loop runs is logged and
    dropped, and a publish that fails after scheduling is logged via a done-callback: SSE cues are
    best-effort and never break the work that raised them.
    """
    if loop is None:
        _log.warning("event loop unavailable; dropping %s", event["type"])
        return
    for channel in channels:
        future = asyncio.run_coroutine_threadsafe(_publish(bus, channel, event), loop)
        future.add_done_callback(_log_publish_failure(event["type"]))


def _schedule_publish(app, channels, event) -> None:
    """Schedule a publish onto the loop and bus the running application holds."""
    _schedule(
        getattr(app.state, "event_loop", None), getattr(app.state, "event_bus", None), channels, event
    )


def _appointment_changed(appointment_id, customer_id, technician_id):
    """Return the channels an appointment change is addressed to, and the cue itself."""
    return (
        (user_channel(customer_id), user_channel(technician_id), ADMINS_CHANNEL),
        {"type": APPOINTMENT_CHANGED, "appointment_id": str(appointment_id)},
    )


def publish_appointment_changed(app, *, appointment_id, customer_id, technician_id) -> None:
    """Signal that an appointment changed, to both participants and the back office.

    A live-refresh cue, not a source of truth — the DB is authoritative and every list refetches
    on receipt.
    """
    channels, event = _appointment_changed(appointment_id, customer_id, technician_id)
    _schedule_publish(app, channels, event)


def publish_appointment_changed_on(
    loop, bus, *, appointment_id, customer_id, technician_id
) -> None:
    """Raise the appointment-changed cue with a bus and loop given directly.

    For a process holding no application to carry the publish, which is the only difference from
    publish_appointment_changed.
    """
    channels, event = _appointment_changed(appointment_id, customer_id, technician_id)
    _schedule(loop, bus, channels, event)


def publish_kb_ingest_progress(
    app, *, user_id, filename, phase: str, done: int, total: int
) -> None:
    """Report how far a knowledge-base ingest has got, to the admin who started it.

    phase names the stage the counts belong to: done/total are pages while "extracting" and
    chunks while "indexing". Addressed to the uploader's own channel rather than the admins
    channel, so a second administrator's panel is not driven by someone else's upload. The
    reporting adapters batch their reports, not once per unit, because a large manual runs to
    hundreds of pages and four figures of chunks.

    Carries the filename rather than a document id: the id is minted inside the ingest and the
    row is not committed while progress is running, so the uploader learns it from the refreshed
    document list once the request returns.
    """
    _schedule_publish(
        app,
        (user_channel(user_id),),
        {
            "type": KB_INGEST_PROGRESS,
            "filename": filename,
            "phase": phase,
            "done": done,
            "total": total,
        },
    )
