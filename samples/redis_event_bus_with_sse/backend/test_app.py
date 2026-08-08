"""Round-trip test for the sample backend: a posted message reaches a sample-channel subscriber.

Runs on the in-process bus (no REDIS_URL), so it proves the app's own wiring — route, channel,
event shape — without a broker. The docker-compose stack is what exercises the Redis path, with
the publish and the subscription in different processes.

Run with the backend virtualenv, which holds every dependency the app imports:
    cd samples/redis_event_bus_with_sse/backend && ../../../backend/.venv/bin/pytest test_app.py
"""
from __future__ import annotations

import asyncio

import httpx

from app import SAMPLE_CHANNEL, create_app


def test_posted_message_reaches_a_sample_channel_subscriber():
    async def scenario():
        app = create_app()
        async with app.state.event_bus.subscribe({SAMPLE_CHANNEL}) as queue:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://sample") as client:
                response = await client.post("/api/publish", json={"message": "hello"})
            assert response.status_code == 200
            return await asyncio.wait_for(queue.get(), timeout=0.5)

    event = asyncio.run(scenario())
    assert event == {"type": "sample.message", "message": "hello"}
