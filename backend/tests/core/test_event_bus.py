"""Tests for the in-process event bus and bus selection.

Fan-out is per channel: a subscriber receives an event only when it opened that event's channel,
which is the property applications build their delivery boundaries on.
"""
from __future__ import annotations

import asyncio

from fsm.core.events import InMemoryEventBus, RedisEventBus, build_event_bus


def _drain(bus: InMemoryEventBus, channels: set[str], publish_channel: str, event: dict):
    """Subscribe to channels, publish one event, return whatever the subscriber received (or None)."""

    async def scenario():
        received: list[dict] = []
        async with bus.subscribe(channels) as queue:
            await bus.publish(publish_channel, event)
            try:
                received.append(await asyncio.wait_for(queue.get(), timeout=0.5))
            except asyncio.TimeoutError:
                pass
        return received

    return asyncio.run(scenario())


class TestInMemoryEventBus:
    def test_subscriber_receives_event_on_its_channel(self):
        bus = InMemoryEventBus()
        event = {"type": "technician_access.requested", "user_id": "x"}
        received = _drain(bus, {"admins"}, "admins", event)
        assert received == [event]

    def test_subscriber_does_not_receive_event_on_other_channel(self):
        bus = InMemoryEventBus()
        received = _drain(bus, {"user:1"}, "admins", {"type": "technician_access.requested"})
        assert received == []

    def test_unsubscribed_after_context_exit(self):
        bus = InMemoryEventBus()
        self_received = _drain(bus, {"admins"}, "admins", {"type": "x"})
        assert self_received  # sanity: delivery worked inside the context
        assert bus.subscriber_count == 0


class TestBuildEventBus:
    def test_without_a_broker_url_the_bus_stays_in_process(self):
        assert isinstance(build_event_bus(None), InMemoryEventBus)

    def test_a_broker_url_selects_the_cross_process_bus(self):
        # from_url resolves lazily, so no server is contacted here.
        assert isinstance(build_event_bus("redis://localhost:6379/0"), RedisEventBus)
