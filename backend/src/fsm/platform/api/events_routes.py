"""Server-Sent Events stream for live in-app delivery.

Each consuming client component opens its own authenticated stream, so one browser tab may hold
several. Every log line a stream writes carries a short random per-connection id, which is what
keeps simultaneous streams of the same user tellable apart when tracing delivery. The server
subscribes the connection only to the channels the caller may subscribe to (their own user
channel, plus the admins channel for an approved administrator), so a client cannot listen in on
back-office events by asking. Events are JSON and framed as `event: <type>` / `data: <json>`;
periodic comment lines keep the connection alive.
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
    open, its deliveries, and its close together across interleaved output.
    """
    bus = request.app.state.event_bus
    channels = subscribable_channels(user)
    stream_id = uuid.uuid4().hex[:8]

    async def stream():
        async with bus.subscribe(channels) as queue:
            _log.info(
                "SSE stream %s opened for user %s on channels %s",
                stream_id, user.id, sorted(channels),
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
                    _log.info(
                        "delivering %s to client user %s on stream %s",
                        event["type"], user.id, stream_id,
                    )
                    yield f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"
            finally:
                _log.info("SSE stream %s closed for user %s", stream_id, user.id)

    return StreamingResponse(stream(), media_type="text/event-stream")
