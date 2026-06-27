"""Server-Sent Events stream for live in-app delivery.

A single authenticated stream per browser tab. The server subscribes the connection only to the
channels the caller is entitled to (their own user channel, plus the admins channel for an approved
administrator), so a client cannot listen in on back-office events by asking. Events are JSON and
framed as ``event: <type>`` / ``data: <json>``; periodic comment lines keep the connection alive.
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from fsm.platform.api.auth_deps import SessionUser, require_user
from fsm.platform.events import entitled_channels

router = APIRouter(prefix="/api")

_KEEPALIVE_SECONDS = 15.0


@router.get("/events")
async def events(request: Request, user: SessionUser = Depends(require_user)) -> StreamingResponse:
    """Open the caller's SSE stream over the channels they are entitled to."""
    bus = request.app.state.event_bus
    channels = entitled_channels(user)

    async def stream():
        async with bus.subscribe(channels) as queue:
            while True:
                if await request.is_disconnected():
                    return
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=_KEEPALIVE_SECONDS)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")
