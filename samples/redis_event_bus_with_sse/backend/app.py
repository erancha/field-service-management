"""Sample backend exposing the FSM event bus over an unauthenticated SSE stream and a publish route.

Every process running this app serves both routes; which process a request reaches is decided by
the sample frontend's proxy, which pins the SSE stream to backend-1 and the publish POST to
backend-2 — so a posted event always crosses processes through the broker before it is delivered.

The bus itself is the FSM app's own transport, imported from fsm.core.events; only the SSE
delivery loop is restated here, because the FSM app's route is inseparable from its session auth.
One fixed channel stands in for the FSM app's per-user and admins channels: channel naming is the
subscribing application's job, and this sample has exactly one audience.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from fsm.core.events import build_event_bus
from fsm.platform.logging import configure_logging

_log = logging.getLogger(__name__)

SAMPLE_CHANNEL = "sample"
SAMPLE_EVENT_TYPE = "sample.message"

_KEEPALIVE_SECONDS = 15.0


class PublishBody(BaseModel):
    """Body of the publish route: the message to fan out on the sample channel."""

    message: str


def create_app() -> FastAPI:
    """Build the sample app; REDIS_URL selects the cross-process bus, its absence the in-process
    one.

    Logging goes through the FSM app's structured configuration, so FSM_LOG_LEVEL and
    FSM_LOG_LEVELS steer this process exactly as they steer the main stack's.
    """
    configure_logging()
    app = FastAPI()
    app.state.event_bus = build_event_bus(os.environ.get("REDIS_URL"))

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.post("/api/publish")
    async def publish(body: PublishBody, request: Request) -> dict:
        event = {"type": SAMPLE_EVENT_TYPE, "message": body.message}
        await request.app.state.event_bus.publish(SAMPLE_CHANNEL, event)
        return event

    @app.get("/api/events")
    async def events(request: Request) -> StreamingResponse:
        """Open an SSE stream over the sample channel.

        Mirrors the FSM app's /api/events route (fsm.platform.api.events_routes) minus its session
        auth: each event is written as an "event: <type>" line naming the event type followed by a
        "data: <json>" line carrying the payload. The per-connection stream id ties the open, each delivery, and the close together in the
        logs, and labels the bus subscription so the bus-side trace lines carry the same id. A
        keepalive comment goes out whenever the interval passes without an event, and every pass
        re-checks the client, so an abandoned stream is unsubscribed within one quiet interval.
        """
        bus = request.app.state.event_bus
        stream_id = uuid.uuid4().hex[:8]

        async def stream():
            async with bus.subscribe({SAMPLE_CHANNEL}, stream_id=stream_id) as queue:
                _log.info("SSE stream '%s' opened on channel '%s'", stream_id, SAMPLE_CHANNEL)
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
                    _log.info("SSE stream '%s' closed", stream_id)

        return StreamingResponse(stream(), media_type="text/event-stream")

    return app
