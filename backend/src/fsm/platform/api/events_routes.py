"""Server-Sent Events stream for live in-app delivery.

Subscribing components in the browser share one authenticated stream per open page, so
simultaneous streams of one user mean several open pages. Every log line a stream writes carries
a short random per-connection id, which is what keeps those streams tellable apart when tracing
delivery. The server subscribes the connection only to the channels the caller may subscribe to
(their own user channel, plus the admins channel for an approved administrator), so a client
cannot listen in on back-office events by asking. The delivery loop sleeps on the subscription's
queue and frames each event it wakes for as `event: <type>` / `data: <json>`; when the keepalive
interval passes without one it emits a comment line instead, which keeps proxies from closing an
idle connection, and every pass re-checks the client, so an abandoned stream is unsubscribed
within one quiet interval at most.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from fsm.platform.api.auth_deps import SessionUser, require_user
from fsm.platform.events import subscribable_channels

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

_KEEPALIVE_SECONDS = 15.0


@router.get("/events")
async def events(request: Request, user: SessionUser = Depends(require_user)) -> StreamingResponse:
    """Open the caller's SSE stream over the channels they may subscribe to.

    The stream id is random per connection and appears in every line this stream logs, tying an
    open, its deliveries, and its close together across interleaved output. It also labels the bus
    subscription, so the bus-side delivery-trace lines carry the same id.
    """
    bus = request.app.state.event_bus
    channels = subscribable_channels(user)
    stream_id = uuid.uuid4().hex[:8]
    sorted_channels = sorted(channels)

    async def stream():
        async with bus.subscribe(channels, stream_id=stream_id) as queue:
            _log.info(
                "SSE stream '%s' opened. Subscribed channels: %s",
                stream_id, sorted_channels,
            )
            try:
                while True:
                    if await request.is_disconnected():
                        return
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=_KEEPALIVE_SECONDS)
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    _log.info("Delivering '%s' on stream '%s'", event["type"], stream_id)
                    yield f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"
            finally:
                _log.info(
                    "SSE stream '%s' closed. Subscribed channels: %s", stream_id, sorted_channels
                )

    return StreamingResponse(stream(), media_type="text/event-stream")
