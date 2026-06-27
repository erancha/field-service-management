"""Process-local and Redis-backed event bus feeding Server-Sent Events.

An event is a JSON-serialisable dict carrying a ``type`` and is published to a named channel.
Two channel shapes exist: ``user:{id}`` (delivered only to that user's streams) and ``admins``
(delivered to every connected back-office stream). Channel membership is the entitlement boundary —
a stream only ever receives events for channels it is allowed to subscribe to (see entitled_channels).

InMemoryEventBus fans out within a single process and is used in host mode and tests. RedisEventBus
carries events between the per-role processes (customer/technician/back-office) of the container
deployment, where an in-process bus cannot reach across process boundaries.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import dataclass, field
from typing import AsyncIterator, Protocol

from fsm.identity.domain.role import Role
from fsm.identity.domain.role_status import RoleStatus
from fsm.platform.api.auth_deps import SessionUser

ADMINS_CHANNEL = "admins"


def user_channel(user_id) -> str:
    """Channel carrying events addressed to a single user."""
    return f"user:{user_id}"


def entitled_channels(user: SessionUser) -> set[str]:
    """Channels a stream for this caller may subscribe to.

    Every caller listens on their own user channel; only an APPROVED administrator additionally
    listens on the back-office channel, so a customer stream can never receive admins events.
    """
    channels = {user_channel(user.id)}
    if user.role is Role.ADMIN and user.role_status is RoleStatus.APPROVED:
        channels.add(ADMINS_CHANNEL)
    return channels


class EventBus(Protocol):
    """Publish/subscribe boundary decoupling event producers from SSE streams."""

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
    """Cross-process fan-out over Redis pub/sub, so events reach streams in other role processes.

    Each event is published as JSON on its channel; a subscription opens a Redis pubsub on the
    requested channels and yields decoded events. Used when REDIS_URL is configured.
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


def build_event_bus(settings) -> EventBus:
    """Return a Redis-backed bus when REDIS_URL is configured, else the in-process bus."""
    redis_url = getattr(settings, "redis_url", None)
    if redis_url:
        import redis.asyncio as redis

        return RedisEventBus(redis.from_url(redis_url, decode_responses=True))
    return InMemoryEventBus()


async def publish_to_app(app, channel: str, event: dict) -> None:
    """Publish to the app's configured event bus; a no-op when none is wired (e.g. some tests)."""
    bus = getattr(app.state, "event_bus", None)
    if bus is not None:
        await bus.publish(channel, event)
