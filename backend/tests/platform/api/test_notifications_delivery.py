"""Integration test: booking via POST /appointments creates notification rows.

Verifies that after a successful booking, one shared notification_event backs a
notification_recipient row for both the customer and technician user_ids. SMTP is unconfigured
so the LoggingEmailSender fallback is used; the in-app feed write is the assertion target.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from testcontainers.postgres import PostgresContainer

from fsm.platform.app import create_app


@pytest.fixture(scope="module")
def pg_session_factory():
    with PostgresContainer("postgres:16", driver="psycopg") as pg:
        url = pg.get_connection_url()
        os.environ["DATABASE_URL"] = url

        cfg = AlembicConfig()
        cfg.set_main_option(
            "script_location",
            str(__import__("pathlib").Path(__file__).parents[3] / "alembic"),
        )
        cfg.set_main_option("sqlalchemy.url", url)
        alembic_command.upgrade(cfg, "head")

        engine = create_engine(url)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        yield factory
        engine.dispose()
        del os.environ["DATABASE_URL"]


@pytest.fixture(scope="module")
def client(pg_session_factory):
    app = create_app(session_factory=pg_session_factory)
    return TestClient(app)


def _utc_iso(year: int, month: int, day: int, hour: int) -> str:
    return datetime(year, month, day, hour, tzinfo=timezone.utc).isoformat()


class TestNotificationsDelivery:
    def test_book_appointment_creates_notification_rows_for_both_parties(
        self, client, pg_session_factory
    ):
        from fsm.notifications.adapters.orm import (
            NotificationEventRow,
            NotificationRecipientRow,
        )
        from fsm.identity.adapters.orm import UserRow
        from fsm.platform.api.auth_deps import require_user, SessionUser
        from fsm.identity.domain.role import Role

        # Authenticate as the customer; booking derives customer_id from the session.
        cust_id = uuid.uuid4()
        tech_id = uuid.uuid4()

        # Booking requires the customer to have an address+phone and the technician a phone.
        with pg_session_factory() as seed:
            with seed.begin():
                seed.add(UserRow(
                    id=cust_id, google_sub=f"sub-{cust_id}", email="cust@example.com",
                    name="Ada Lovelace", role=Role.CUSTOMER.value, role_status="APPROVED",
                    address="12 Main St", phone="+972-50-100",
                ))
                seed.add(UserRow(
                    id=tech_id, google_sub=f"sub-{tech_id}", email="tech@example.com",
                    name="Grace Hopper", role=Role.TECHNICIAN.value, role_status="APPROVED",
                    phone="+972-50-200",
                ))

        client.app.dependency_overrides[require_user] = lambda: SessionUser(
            id=cust_id, role=Role.CUSTOMER, email="cust@example.com"
        )
        try:
            sc_resp = client.post(
                "/api/service-calls",
                json={"description": "Notification test"},
            )
            assert sc_resp.status_code == 201
            sc_id = sc_resp.json()["id"]

            book_resp = client.post(
                "/api/appointments",
                json={
                    "service_call_id": sc_id,
                    "technician_id": str(tech_id),
                    "start": _utc_iso(2025, 7, 6, 9),
                    "end": _utc_iso(2025, 7, 6, 10),
                },
            )
            assert book_resp.status_code == 200
            appt_id = book_resp.json()["id"]
        finally:
            client.app.dependency_overrides.pop(require_user, None)

        def recipient_event(sess, user_id):
            return (
                sess.query(NotificationRecipientRow, NotificationEventRow)
                .join(
                    NotificationEventRow,
                    NotificationRecipientRow.notification_event_id == NotificationEventRow.id,
                )
                .filter(NotificationRecipientRow.user_id == user_id)
                .all()
            )

        with pg_session_factory() as sess:
            cust_rows = recipient_event(sess, cust_id)
            tech_rows = recipient_event(sess, tech_id)

        assert len(cust_rows) == 1, "Expected one notification recipient row for the customer"
        assert len(tech_rows) == 1, "Expected one notification recipient row for the technician"
        cust_recipient, cust_event = cust_rows[0]
        tech_recipient, tech_event = tech_rows[0]

        # Both parties hang off the single shared event, storing the booking body only once.
        assert cust_event.id == tech_event.id
        assert cust_event.kind == "BOOKED"
        assert cust_event.subject == "Appointment booked — Notification test"
        assert "Problem: Notification test" in cust_event.body
        assert "Technician: Grace Hopper" in cust_event.body
        assert "Technician phone: +972-50-200" in cust_event.body
        assert str(appt_id) not in cust_event.body
