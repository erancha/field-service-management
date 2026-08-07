"""Tests for which channels a caller may subscribe to, and the cues published onto FSM's channels.

Channel membership is what enforces that a customer's event stream never receives back-office
(admins) events; the fan-out itself is covered in tests/core/test_event_bus.py.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from types import SimpleNamespace

from fsm.core.events_memory import InMemoryEventBus
from fsm.identity.domain.role import Role
from fsm.identity.domain.role_status import RoleStatus
from fsm.platform.api.auth_deps import SessionUser
from fsm.platform.events import (
    ADMINS_CHANNEL,
    publish_appointment_changed,
    publish_kb_ingest_progress,
    subscribable_channels,
    user_channel,
)


class TestPublishAppointmentChanged:
    def test_publishes_to_both_participants_and_admins(self):
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
        app = SimpleNamespace(state=SimpleNamespace(event_bus=InMemoryEventBus(), event_loop=None))
        # No loop captured yet: this must not raise.
        publish_appointment_changed(app, appointment_id=uuid.uuid4(), customer_id=uuid.uuid4(), technician_id=uuid.uuid4())

    def test_logs_when_scheduled_publish_raises(self, caplog):
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


class TestPublishKbIngestProgress:
    def test_reaches_the_uploading_admin_and_not_the_admins_channel(self):
        """Progress is addressed to the uploader so a second admin's panel is not driven by it."""

        async def scenario():
            bus = InMemoryEventBus()
            app = SimpleNamespace(
                state=SimpleNamespace(event_bus=bus, event_loop=asyncio.get_running_loop())
            )
            uploader = uuid.uuid4()

            async with bus.subscribe({user_channel(uploader)}) as mine:
                async with bus.subscribe({ADMINS_CHANNEL}) as others:
                    # Publishing from a worker thread is the real call path: the ingest runs in
                    # the threadpool, not on the loop.
                    await asyncio.to_thread(
                        publish_kb_ingest_progress,
                        app,
                        user_id=uploader,
                        filename="manual.pdf",
                        phase="indexing",
                        done=64,
                        total=1007,
                    )
                    event = await asyncio.wait_for(mine.get(), timeout=0.5)
                    return event, others.empty()

        event, admins_empty = asyncio.run(scenario())
        assert event == {
            "type": "kb.ingest.progress",
            "filename": "manual.pdf",
            "phase": "indexing",
            "done": 64,
            "total": 1007,
        }
        assert admins_empty

    def test_drops_when_loop_absent(self):
        app = SimpleNamespace(state=SimpleNamespace(event_bus=InMemoryEventBus(), event_loop=None))
        # No loop captured yet: a progress cue must not break the ingest.
        publish_kb_ingest_progress(
            app, user_id=uuid.uuid4(), filename="manual.pdf", phase="indexing", done=1, total=2
        )


class TestSubscribableChannels:
    def test_customer_gets_only_their_own_user_channel(self):
        uid = uuid.uuid4()
        user = SessionUser(id=uid, role=Role.CUSTOMER, email=None, role_status=RoleStatus.APPROVED)
        assert subscribable_channels(user) == {f"user:{uid}"}

    def test_approved_admin_also_gets_admins_channel(self):
        uid = uuid.uuid4()
        user = SessionUser(id=uid, role=Role.ADMIN, email=None, role_status=RoleStatus.APPROVED)
        assert subscribable_channels(user) == {f"user:{uid}", "admins"}

    def test_unapproved_admin_does_not_get_admins_channel(self):
        uid = uuid.uuid4()
        user = SessionUser(id=uid, role=Role.ADMIN, email=None, role_status=RoleStatus.PENDING)
        assert subscribable_channels(user) == {f"user:{uid}"}
