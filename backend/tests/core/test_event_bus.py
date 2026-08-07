"""Tests for the in-process event bus and bus selection.

Fan-out is per channel: a subscriber receives an event only when it opened that event's channel,
which is the property applications build their delivery boundaries on.
"""
from __future__ import annotations

import asyncio
import logging

from fsm.core.events import RedisEventBus, build_event_bus
from fsm.core.events_memory import InMemoryEventBus


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

    def test_publish_log_names_the_delivered_streams(self, caplog):
        bus = InMemoryEventBus()

        async def scenario():
            async with bus.subscribe({"admins"}, stream_id="ab12cd34") as queue:
                with caplog.at_level(logging.INFO, logger="fsm.core.events_memory"):
                    await bus.publish("admins", {"type": "x"})
                await asyncio.wait_for(queue.get(), timeout=0.5)

        asyncio.run(scenario())
        assert "'ab12cd34'" in caplog.text


class _FakePubSub:
    """In-process stand-in for redis.asyncio pubsub: listen drains the queue _FakeRedis.publish feeds."""

    def __init__(self) -> None:
        self.messages: "asyncio.Queue[dict]" = asyncio.Queue()

    async def subscribe(self, *channels: str) -> None:
        pass

    async def unsubscribe(self, *channels: str) -> None:
        pass

    async def aclose(self) -> None:
        pass

    async def listen(self):
        while True:
            yield await self.messages.get()


class _FakeRedis:
    """Routes publishes straight into the single pubsub's message queue."""

    def __init__(self) -> None:
        self.pubsub_instance = _FakePubSub()

    def pubsub(self) -> _FakePubSub:
        return self.pubsub_instance

    async def publish(self, channel: str, data: str) -> int:
        await self.pubsub_instance.messages.put(
            {"type": "message", "channel": channel, "data": data}
        )
        return 1


class TestRedisEventBus:
    def test_publish_log_counts_subscribers(self, caplog):
        bus = RedisEventBus(_FakeRedis())

        async def scenario():
            with caplog.at_level(logging.INFO, logger="fsm.core.events"):
                await bus.publish("admins", {"type": "x"})

        asyncio.run(scenario())
        assert "Published 'x' to 'admins' (1 subscriber(s))" in caplog.text

    def test_receipt_log_names_the_stream(self, caplog):
        bus = RedisEventBus(_FakeRedis())

        async def scenario():
            with caplog.at_level(logging.INFO, logger="fsm.core.events"):
                async with bus.subscribe({"admins"}, stream_id="ab12cd34") as queue:
                    await bus.publish("admins", {"type": "x"})
                    return await asyncio.wait_for(queue.get(), timeout=0.5)

        event = asyncio.run(scenario())
        assert event == {"type": "x"}
        assert "Received 'x' from 'admins' to the queue of stream 'ab12cd34'" in caplog.text


class TestBuildEventBus:
    def test_without_a_broker_url_the_bus_stays_in_process(self):
        assert isinstance(build_event_bus(None), InMemoryEventBus)

    def test_a_broker_url_selects_the_cross_process_bus(self):
        # from_url resolves lazily, so no server is contacted here.
        assert isinstance(build_event_bus("redis://localhost:6379/0"), RedisEventBus)
