"""Tests for the in-memory event bus and SSE channel entitlement.

The bus fans an event out only to subscribers listening on its channel, which is what enforces
that a customer's event stream never receives back-office (admins) events.
"""
from __future__ import annotations

import asyncio
import uuid

from fsm.identity.domain.role import Role
from fsm.identity.domain.role_status import RoleStatus
from fsm.platform.api.auth_deps import SessionUser
from fsm.platform.events import InMemoryEventBus, entitled_channels


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


class TestEntitledChannels:
    def test_customer_gets_only_their_own_user_channel(self):
        uid = uuid.uuid4()
        user = SessionUser(id=uid, role=Role.CUSTOMER, email=None, role_status=RoleStatus.APPROVED)
        assert entitled_channels(user) == {f"user:{uid}"}

    def test_approved_admin_also_gets_admins_channel(self):
        uid = uuid.uuid4()
        user = SessionUser(id=uid, role=Role.ADMIN, email=None, role_status=RoleStatus.APPROVED)
        assert entitled_channels(user) == {f"user:{uid}", "admins"}

    def test_unapproved_admin_does_not_get_admins_channel(self):
        uid = uuid.uuid4()
        user = SessionUser(id=uid, role=Role.ADMIN, email=None, role_status=RoleStatus.PENDING)
        assert entitled_channels(user) == {f"user:{uid}"}
