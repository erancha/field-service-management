"""Publish/subscribe transport for pushing events to live streams.

An event is a JSON-serialisable dict published to a named channel; a subscriber receives only
events on the channels it opened, which is what lets callers use channel membership as a delivery
boundary. Naming the channels and deciding who may subscribe to which is the application's job,
not this module's.

RedisEventBus carries events between processes and is required wherever the streams that must see
an event live outside the publishing process. InMemoryEventBus fans out within a single process
and backs test suites and any single-process run started without a broker configured.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import dataclass, field
from typing import AsyncIterator, Protocol


class EventBus(Protocol):
    """Publish/subscribe boundary decoupling event producers from the streams that consume them."""

    async def publish(self, channel: str, event: dict) -> None:
        """Deliver event to every current subscriber listening on channel."""
        ...

    def subscribe(self, channels: set[str]):
        """Async context manager yielding an async iterator of events for the given channels."""
        ...


@dataclass(eq=False)
class _Subscription:
    channels: set[str]
    queue: "asyncio.Queue[dict]" = field(default_factory=asyncio.Queue)


class InMemoryEventBus:
    """Single-process fan-out: delivers each event to every subscriber listening on its channel."""

    def __init__(self) -> None:
        self._subscribers: set[_Subscription] = set()

    @property
    def subscriber_count(self) -> int:
        """Number of active subscriptions (test/observability helper)."""
        return len(self._subscribers)

    async def publish(self, channel: str, event: dict) -> None:
        for sub in list(self._subscribers):
            if channel in sub.channels:
                sub.queue.put_nowait(event)

    @contextlib.asynccontextmanager
    async def subscribe(self, channels: set[str]) -> AsyncIterator["asyncio.Queue[dict]"]:
        sub = _Subscription(channels=set(channels))
        self._subscribers.add(sub)
        try:
            yield sub.queue
        finally:
            self._subscribers.discard(sub)


class RedisEventBus:
    """Cross-process fan-out over Redis pub/sub, so events reach streams in other processes.

    Each event is published as JSON on its channel; a subscription opens a Redis pubsub on the
    requested channels and yields decoded events.
    """

    def __init__(self, client) -> None:
        self._redis = client

    async def publish(self, channel: str, event: dict) -> None:
        await self._redis.publish(channel, json.dumps(event))

    @contextlib.asynccontextmanager
    async def subscribe(self, channels: set[str]) -> AsyncIterator["asyncio.Queue[dict]"]:
        queue: "asyncio.Queue[dict]" = asyncio.Queue()
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(*channels)

        async def _pump() -> None:
            async for message in pubsub.listen():
                if message.get("type") == "message":
                    queue.put_nowait(json.loads(message["data"]))

        pump_task = asyncio.create_task(_pump())
        try:
            yield queue
        finally:
            pump_task.cancel()
            with contextlib.suppress(Exception):
                await pubsub.unsubscribe(*channels)
                await pubsub.aclose()


def build_event_bus(redis_url: str | None) -> EventBus:
    """Return a Redis-backed bus when a broker URL is given, else the in-process bus."""
    if redis_url:
        import redis.asyncio as redis

        return RedisEventBus(redis.from_url(redis_url, decode_responses=True))
    return InMemoryEventBus()
