"""Tests for the in-memory event bus and SSE channel entitlement.

The bus fans an event out only to subscribers listening on its channel, which is what enforces
that a customer's event stream never receives back-office (admins) events.
"""
from __future__ import annotations

import asyncio
import logging
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


class TestPublishAppointmentChanged:
    def test_publishes_to_both_participants_and_admins(self):
        import asyncio
        from types import SimpleNamespace
        from fsm.platform.events import (
            ADMINS_CHANNEL, InMemoryEventBus, publish_appointment_changed, user_channel,
        )

        async def scenario():
            bus = InMemoryEventBus()
            loop = asyncio.get_running_loop()
            app = SimpleNamespace(state=SimpleNamespace(event_bus=bus, event_loop=loop))
            cust, tech, appt = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

            channels = {user_channel(cust), user_channel(tech), ADMINS_CHANNEL}
            async with bus.subscribe(channels) as queue:
                publish_appointment_changed(app, appointment_id=appt, customer_id=cust, technician_id=tech)
                received = [await asyncio.wait_for(queue.get(), timeout=0.5) for _ in range(3)]
            return received, appt

        received, appt = asyncio.run(scenario())
        assert all(e == {"type": "appointment.changed", "appointment_id": str(appt)} for e in received)

    def test_drops_when_loop_absent(self):
        from types import SimpleNamespace
        from fsm.platform.events import InMemoryEventBus, publish_appointment_changed

        app = SimpleNamespace(state=SimpleNamespace(event_bus=InMemoryEventBus(), event_loop=None))
        # No loop captured yet: this must not raise.
        publish_appointment_changed(app, appointment_id=uuid.uuid4(), customer_id=uuid.uuid4(), technician_id=uuid.uuid4())

    def test_logs_when_scheduled_publish_raises(self, caplog):
        from types import SimpleNamespace
        from fsm.platform.events import publish_appointment_changed

        class FailingBus:
            async def publish(self, channel, event):
                raise RuntimeError("boom")

        async def scenario():
            loop = asyncio.get_running_loop()
            app = SimpleNamespace(state=SimpleNamespace(event_bus=FailingBus(), event_loop=loop))
            publish_appointment_changed(
                app, appointment_id=uuid.uuid4(), customer_id=uuid.uuid4(), technician_id=uuid.uuid4()
            )
            # Give the loop room to run the scheduled coroutines and their done-callbacks.
            await asyncio.sleep(0.1)

        with caplog.at_level(logging.WARNING, logger="fsm.platform.events"):
            asyncio.run(scenario())

        assert "appointment.changed publish failed" in caplog.text


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
