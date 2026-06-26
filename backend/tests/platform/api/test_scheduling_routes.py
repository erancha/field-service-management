"""Integration tests for the scheduling API endpoints.

A Postgres 16 container is started once per module. Alembic migrations are
applied to it once. Each test uses a real TestClient so that the full
request/response path — including FastAPI routing, Pydantic validation,
domain use-cases, UoW, and SQL persistence — is exercised end-to-end.

Test isolation: each test that writes to the DB uses a unique technician_id
or service_call_id so tests don't collide. The module-level container is not
rolled back between tests; the Postgres exclusion constraint is exercised
by intentionally overlapping appointments.
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


# ---------------------------------------------------------------------------
# Module-scoped container + migrated engine
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pg_session_factory():
    """Start a Postgres 16 container, run migrations, yield a session factory."""
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
    """Return a TestClient wired to the migrated Postgres container."""
    app = create_app(session_factory=pg_session_factory)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_iso(year: int, month: int, day: int, hour: int) -> str:
    return datetime(year, month, day, hour, tzinfo=timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# 1. Open a service call
# ---------------------------------------------------------------------------


def test_open_service_call_returns_201(client):
    payload = {
        "customer_id": str(uuid.uuid4()),
        "description": "Fix broken boiler",
        "category": "plumbing",
    }
    response = client.post("/api/service-calls", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["description"] == "Fix broken boiler"
    assert data["category"] == "plumbing"
    assert data["status"] == "OPEN"
    assert uuid.UUID(data["id"])


# ---------------------------------------------------------------------------
# 2. Query availability
# ---------------------------------------------------------------------------


def test_availability_returns_slots(client):
    tech_id = uuid.uuid4()
    response = client.get(
        "/api/availability",
        params={
            "technician_id": str(tech_id),
            "date_from": "2025-01-05",  # Sunday (Israeli work week)
            "date_to": "2025-01-05",
            "slot_minutes": 60,
            "tz": "Asia/Jerusalem",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "slots" in data
    # Default schedule: Sun–Thu 09:00–17:00 = 8 one-hour slots per day
    assert len(data["slots"]) == 8
    # Each slot must have start and end
    for slot in data["slots"]:
        assert "start" in slot
        assert "end" in slot


def test_availability_friday_returns_no_slots(client):
    """Friday is not a working day in the default Israeli schedule."""
    tech_id = uuid.uuid4()
    response = client.get(
        "/api/availability",
        params={
            "technician_id": str(tech_id),
            "date_from": "2025-01-03",  # Friday
            "date_to": "2025-01-03",
            "slot_minutes": 60,
            "tz": "Asia/Jerusalem",
        },
    )
    assert response.status_code == 200
    assert response.json()["slots"] == []


def test_availability_invalid_timezone_returns_400(client):
    response = client.get(
        "/api/availability",
        params={
            "technician_id": str(uuid.uuid4()),
            "date_from": "2025-01-05",
            "date_to": "2025-01-05",
            "tz": "Fake/Timezone",
        },
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# 3. Book an appointment
# ---------------------------------------------------------------------------


def test_book_appointment_returns_200_and_is_persisted(client, pg_session_factory):
    # Open a service call first
    sc_resp = client.post(
        "/api/service-calls",
        json={
            "customer_id": str(uuid.uuid4()),
            "description": "AC repair",
            "category": "hvac",
        },
    )
    assert sc_resp.status_code == 201
    sc_id = sc_resp.json()["id"]

    tech_id = uuid.uuid4()
    cust_id = uuid.uuid4()

    book_resp = client.post(
        "/api/appointments",
        json={
            "service_call_id": sc_id,
            "technician_id": str(tech_id),
            "customer_id": str(cust_id),
            "start": _utc_iso(2025, 1, 5, 9),
            "end": _utc_iso(2025, 1, 5, 10),
        },
    )
    assert book_resp.status_code == 200
    appt_data = book_resp.json()
    assert appt_data["status"] == "SCHEDULED"
    assert uuid.UUID(appt_data["id"])

    # Verify service call is now SCHEDULED
    from fsm.scheduling.adapters.repositories import SqlAlchemyServiceCallRepository
    from fsm.scheduling.domain.service_call import ServiceCallStatus

    with pg_session_factory() as sess:
        sc_repo = SqlAlchemyServiceCallRepository(sess)
        sc = sc_repo.get(uuid.UUID(sc_id))
        assert sc.status == ServiceCallStatus.SCHEDULED

    # Verify outbox CREATE entry exists
    from fsm.scheduling.adapters.outbox_repository import SqlAlchemyOutboxRepository
    from fsm.scheduling.ports.outbox import OutboxOperation

    with pg_session_factory() as sess:
        outbox = SqlAlchemyOutboxRepository(sess)
        pending = outbox.list_pending(limit=100)
        appt_id = uuid.UUID(appt_data["id"])
        matching = [e for e in pending if e.appointment_id == appt_id]
        assert len(matching) == 1
        assert matching[0].operation == OutboxOperation.CREATE


# ---------------------------------------------------------------------------
# 4. Book overlapping appointment for same technician → 409
# ---------------------------------------------------------------------------


def test_booking_overlapping_slot_returns_409(client):
    # Open two service calls, share the same technician
    tech_id = uuid.uuid4()

    sc1 = client.post(
        "/api/service-calls",
        json={"customer_id": str(uuid.uuid4()), "description": "Job 1", "category": "electric"},
    ).json()
    sc2 = client.post(
        "/api/service-calls",
        json={"customer_id": str(uuid.uuid4()), "description": "Job 2", "category": "electric"},
    ).json()

    # First booking succeeds
    r1 = client.post(
        "/api/appointments",
        json={
            "service_call_id": sc1["id"],
            "technician_id": str(tech_id),
            "customer_id": str(uuid.uuid4()),
            "start": _utc_iso(2025, 2, 2, 10),
            "end": _utc_iso(2025, 2, 2, 12),
        },
    )
    assert r1.status_code == 200

    # Second booking overlaps the first → 409
    r2 = client.post(
        "/api/appointments",
        json={
            "service_call_id": sc2["id"],
            "technician_id": str(tech_id),
            "customer_id": str(uuid.uuid4()),
            "start": _utc_iso(2025, 2, 2, 11),
            "end": _utc_iso(2025, 2, 2, 13),
        },
    )
    assert r2.status_code == 409


# ---------------------------------------------------------------------------
# 5. Reschedule an appointment
# ---------------------------------------------------------------------------


def test_reschedule_appointment_succeeds(client):
    sc = client.post(
        "/api/service-calls",
        json={"customer_id": str(uuid.uuid4()), "description": "Pipe fix", "category": "plumbing"},
    ).json()

    tech_id = uuid.uuid4()
    book = client.post(
        "/api/appointments",
        json={
            "service_call_id": sc["id"],
            "technician_id": str(tech_id),
            "customer_id": str(uuid.uuid4()),
            "start": _utc_iso(2025, 3, 2, 9),
            "end": _utc_iso(2025, 3, 2, 10),
        },
    ).json()

    appt_id = book["id"]
    reschedule_resp = client.post(
        f"/api/appointments/{appt_id}/reschedule",
        json={
            "start": _utc_iso(2025, 3, 3, 9),
            "end": _utc_iso(2025, 3, 3, 11),
        },
    )
    assert reschedule_resp.status_code == 200
    data = reschedule_resp.json()
    assert data["status"] == "RESCHEDULED"
    assert data["id"] == appt_id


# ---------------------------------------------------------------------------
# 6. Cancel an appointment
# ---------------------------------------------------------------------------


def test_cancel_appointment_succeeds(client):
    sc = client.post(
        "/api/service-calls",
        json={"customer_id": str(uuid.uuid4()), "description": "Window seal", "category": "general"},
    ).json()

    tech_id = uuid.uuid4()
    book = client.post(
        "/api/appointments",
        json={
            "service_call_id": sc["id"],
            "technician_id": str(tech_id),
            "customer_id": str(uuid.uuid4()),
            "start": _utc_iso(2025, 4, 6, 14),
            "end": _utc_iso(2025, 4, 6, 15),
        },
    ).json()

    appt_id = book["id"]
    cancel_resp = client.post(f"/api/appointments/{appt_id}/cancel")
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "CANCELLED"


# ---------------------------------------------------------------------------
# 7. Add details
# ---------------------------------------------------------------------------


def test_add_details_succeeds(client):
    sc = client.post(
        "/api/service-calls",
        json={"customer_id": str(uuid.uuid4()), "description": "Leaky tap", "category": "plumbing"},
    ).json()

    tech_id = uuid.uuid4()
    book = client.post(
        "/api/appointments",
        json={
            "service_call_id": sc["id"],
            "technician_id": str(tech_id),
            "customer_id": str(uuid.uuid4()),
            "start": _utc_iso(2025, 5, 4, 10),
            "end": _utc_iso(2025, 5, 4, 11),
        },
    ).json()

    appt_id = book["id"]
    details_resp = client.post(
        f"/api/appointments/{appt_id}/details",
        json={"text": "Bring 3/4 inch wrench"},
    )
    assert details_resp.status_code == 200
    assert details_resp.json()["details"] == "Bring 3/4 inch wrench"


# ---------------------------------------------------------------------------
# Error path: booking against non-existent service call → 404
# ---------------------------------------------------------------------------


def test_book_against_missing_service_call_returns_404(client):
    response = client.post(
        "/api/appointments",
        json={
            "service_call_id": str(uuid.uuid4()),
            "technician_id": str(uuid.uuid4()),
            "customer_id": str(uuid.uuid4()),
            "start": _utc_iso(2025, 6, 1, 9),
            "end": _utc_iso(2025, 6, 1, 10),
        },
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Error path: reschedule non-existent appointment → 404
# ---------------------------------------------------------------------------


def test_reschedule_missing_appointment_returns_404(client):
    response = client.post(
        f"/api/appointments/{uuid.uuid4()}/reschedule",
        json={"start": _utc_iso(2025, 6, 1, 9), "end": _utc_iso(2025, 6, 1, 10)},
    )
    assert response.status_code == 404
