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
import logging
from dataclasses import dataclass, field
from typing import AsyncIterator, Protocol

_log = logging.getLogger(__name__)


class EventBus(Protocol):
    """Publish/subscribe boundary decoupling event producers from the streams that consume them."""

    async def publish(self, channel: str, event: dict) -> None:
        """Deliver event to every current subscriber listening on channel."""
        ...

    def subscribe(self, channels: set[str], stream_id: str | None = None):
        """Async context manager yielding an async iterator of events for the given channels.

        stream_id, when given, names the consuming stream in the delivery-trace log lines.
        """
        ...


@dataclass(eq=False)
class _Subscription:
    channels: set[str]
    queue: "asyncio.Queue[dict]" = field(default_factory=asyncio.Queue)
    stream_id: str | None = None


class InMemoryEventBus:
    """Single-process fan-out: delivers each event to every subscriber listening on its channel."""

    def __init__(self) -> None:
        self._subscribers: set[_Subscription] = set()

    @property
    def subscriber_count(self) -> int:
        """Number of active subscriptions (test/observability helper)."""
        return len(self._subscribers)

    async def publish(self, channel: str, event: dict) -> None:
        delivered = [sub for sub in self._subscribers if channel in sub.channels]
        for sub in delivered:
            sub.queue.put_nowait(event)
        _log.info(
            "Published '%s' to '%s' (%d subscriber(s), streams: %s)",
            event["type"], channel, len(delivered), [sub.stream_id for sub in delivered],
        )

    @contextlib.asynccontextmanager
    async def subscribe(
        self, channels: set[str], stream_id: str | None = None
    ) -> AsyncIterator["asyncio.Queue[dict]"]:
        sub = _Subscription(channels=set(channels), stream_id=stream_id)
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
        subscribers = await self._redis.publish(channel, json.dumps(event))
        _log.info("Published '%s' to '%s' (%d subscriber(s))", event["type"], channel, subscribers)

    @contextlib.asynccontextmanager
    async def subscribe(
        self, channels: set[str], stream_id: str | None = None
    ) -> AsyncIterator["asyncio.Queue[dict]"]:
        queue: "asyncio.Queue[dict]" = asyncio.Queue()
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(*channels)
        trace_suffix = "" if stream_id is None else f" to the queue of stream '{stream_id}'"

        async def _pump() -> None:
            async for message in pubsub.listen():
                if message.get("type") == "message":
                    event = json.loads(message["data"])
                    queue.put_nowait(event)
                    _log.info(
                        "Received '%s' from '%s'%s", event["type"], message["channel"], trace_suffix
                    )

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
