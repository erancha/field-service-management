"""Single-process event bus: fans out within one process, no broker required.

Implements the EventBus protocol from fsm.core.events for test suites and single-process runs
started without a broker configured. build_event_bus imports this module only on that path, so a
Redis-backed deployment never loads it.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from typing import AsyncIterator

_log = logging.getLogger(__name__)


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
            "Published '%s' to channel '%s' (%d subscriber(s), streams: %s)",
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
