"""Integration test: booking via POST /appointments creates notification rows.

Verifies that after a successful booking, the notification table contains rows
for both the customer and technician user_ids. SMTP is unconfigured so the
LoggingEmailSender fallback is used; the in-app feed write is the assertion target.
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
        from fsm.notifications.adapters.orm import NotificationRow

        sc_resp = client.post(
            "/api/service-calls",
            json={
                "customer_id": str(uuid.uuid4()),
                "description": "Notification test",
                "category": "general",
            },
        )
        assert sc_resp.status_code == 201
        sc_id = sc_resp.json()["id"]

        cust_id = uuid.uuid4()
        tech_id = uuid.uuid4()

        book_resp = client.post(
            "/api/appointments",
            json={
                "service_call_id": sc_id,
                "technician_id": str(tech_id),
                "customer_id": str(cust_id),
                "start": _utc_iso(2025, 7, 6, 9),
                "end": _utc_iso(2025, 7, 6, 10),
            },
        )
        assert book_resp.status_code == 200

        with pg_session_factory() as sess:
            cust_rows = (
                sess.query(NotificationRow)
                .filter(NotificationRow.user_id == cust_id)
                .all()
            )
            tech_rows = (
                sess.query(NotificationRow)
                .filter(NotificationRow.user_id == tech_id)
                .all()
            )

        assert len(cust_rows) == 1, "Expected one notification row for the customer"
        assert len(tech_rows) == 1, "Expected one notification row for the technician"
        assert cust_rows[0].kind == "BOOKED"
        assert tech_rows[0].kind == "BOOKED"
