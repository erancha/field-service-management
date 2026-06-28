"""Integration tests for the scheduling API endpoints.

A Postgres 16 container is started once per module. Alembic migrations are
applied to it once. Each test uses a real TestClient so that the full
request/response path — including FastAPI routing, Pydantic validation,
domain use-cases, UoW, and SQL persistence — is exercised end-to-end.

Authentication: every /api route is gated by require_user. Tests authenticate
by overriding that dependency via the `auth` fixture, which stamps a session
user of a chosen id and role; identity is taken from the session, never the
request body. The override is cleared after each test.

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
from fsm.identity.domain.role import Role


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
def app(pg_session_factory):
    """Return the FastAPI app wired to the migrated Postgres container."""
    return create_app(session_factory=pg_session_factory)


@pytest.fixture(scope="module")
def client(app):
    """Return a TestClient. Unauthenticated by default — use `auth` to sign in."""
    return TestClient(app)


@pytest.fixture
def auth(app, authenticate):
    """Bind this module's app to the shared `authenticate` helper.

    Returns `auth(user_id=None, role=Role.CUSTOMER) -> UUID`; calling it again within a
    test switches the active user. The default (no call) leaves the request unauthenticated.
    """
    def _set(user_id: uuid.UUID | None = None, role: Role = Role.CUSTOMER) -> uuid.UUID:
        return authenticate(app, user_id=user_id, role=role)

    return _set


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_iso(year: int, month: int, day: int, hour: int) -> str:
    return datetime(year, month, day, hour, tzinfo=timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# 0. Gating: unauthenticated access is rejected
# ---------------------------------------------------------------------------


def test_unauthenticated_request_returns_401(client):
    """With no session, scheduling routes are not reachable."""
    create = client.post("/api/service-calls", json={"description": "x"})
    assert create.status_code == 401

    read = client.get(
        "/api/availability",
        params={
            "technician_id": str(uuid.uuid4()),
            "date_from": "2025-01-05",
            "date_to": "2025-01-05",
        },
    )
    assert read.status_code == 401


# ---------------------------------------------------------------------------
# 1. Open a service call
# ---------------------------------------------------------------------------


def test_open_service_call_returns_201(client, auth):
    cust_id = auth(role=Role.CUSTOMER)
    response = client.post(
        "/api/service-calls",
        json={"description": "Fix broken boiler"},
    )
    assert response.status_code == 201
    data = response.json()
    # Identity comes from the session, not the body.
    assert data["customer_id"] == str(cust_id)
    assert data["description"] == "Fix broken boiler"
    assert data["status"] == "OPEN"
    assert uuid.UUID(data["id"])


def test_open_service_call_wrong_role_returns_403(client, auth):
    """Only customers may open service calls."""
    auth(role=Role.TECHNICIAN)
    response = client.post(
        "/api/service-calls",
        json={"description": "x"},
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# 2. Query availability
# ---------------------------------------------------------------------------


def test_availability_returns_slots(client, auth):
    auth()
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
    for slot in data["slots"]:
        assert "start" in slot
        assert "end" in slot


def test_availability_friday_returns_no_slots(client, auth):
    """Friday is not a working day in the default Israeli schedule."""
    auth()
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


def test_availability_invalid_timezone_returns_400(client, auth):
    auth()
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


def test_book_appointment_returns_200_and_is_persisted(client, auth, pg_session_factory):
    cust_id = auth(role=Role.CUSTOMER)
    sc_resp = client.post(
        "/api/service-calls",
        json={"description": "AC repair"},
    )
    assert sc_resp.status_code == 201
    sc_id = sc_resp.json()["id"]

    tech_id = uuid.uuid4()
    book_resp = client.post(
        "/api/appointments",
        json={
            "service_call_id": sc_id,
            "technician_id": str(tech_id),
            "start": _utc_iso(2025, 1, 5, 9),
            "end": _utc_iso(2025, 1, 5, 10),
        },
    )
    assert book_resp.status_code == 200
    appt_data = book_resp.json()
    assert appt_data["status"] == "SCHEDULED"
    assert appt_data["customer_id"] == str(cust_id)
    assert uuid.UUID(appt_data["id"])

    from fsm.scheduling.adapters.repositories import SqlAlchemyServiceCallRepository
    from fsm.scheduling.domain.service_call import ServiceCallStatus

    with pg_session_factory() as sess:
        sc_repo = SqlAlchemyServiceCallRepository(sess)
        sc = sc_repo.get(uuid.UUID(sc_id))
        assert sc.status == ServiceCallStatus.SCHEDULED

    from fsm.scheduling.adapters.outbox_repository import SqlAlchemyOutboxRepository
    from fsm.scheduling.ports.outbox import OutboxOperation

    with pg_session_factory() as sess:
        outbox = SqlAlchemyOutboxRepository(sess)
        pending = outbox.list_pending(limit=100)
        appt_id = uuid.UUID(appt_data["id"])
        matching = [e for e in pending if e.appointment_id == appt_id]
        assert len(matching) == 1
        assert matching[0].operation == OutboxOperation.CREATE


def test_book_against_another_customers_service_call_returns_403(client, auth):
    """A customer cannot book against a service call they don't own."""
    owner = auth(role=Role.CUSTOMER)
    sc = client.post(
        "/api/service-calls",
        json={"description": "Owned by someone else"},
    ).json()
    assert sc["customer_id"] == str(owner)

    # Switch to a different customer and try to book against the first one's call.
    auth(user_id=uuid.uuid4(), role=Role.CUSTOMER)
    resp = client.post(
        "/api/appointments",
        json={
            "service_call_id": sc["id"],
            "technician_id": str(uuid.uuid4()),
            "start": _utc_iso(2025, 8, 3, 9),
            "end": _utc_iso(2025, 8, 3, 10),
        },
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 4. Book overlapping appointment for same technician → 409
# ---------------------------------------------------------------------------


def test_booking_overlapping_slot_returns_409(client, auth):
    auth(role=Role.CUSTOMER)
    tech_id = uuid.uuid4()

    sc1 = client.post(
        "/api/service-calls",
        json={"description": "Job 1"},
    ).json()
    sc2 = client.post(
        "/api/service-calls",
        json={"description": "Job 2"},
    ).json()

    r1 = client.post(
        "/api/appointments",
        json={
            "service_call_id": sc1["id"],
            "technician_id": str(tech_id),
            "start": _utc_iso(2025, 2, 2, 10),
            "end": _utc_iso(2025, 2, 2, 12),
        },
    )
    assert r1.status_code == 200

    r2 = client.post(
        "/api/appointments",
        json={
            "service_call_id": sc2["id"],
            "technician_id": str(tech_id),
            "start": _utc_iso(2025, 2, 2, 11),
            "end": _utc_iso(2025, 2, 2, 13),
        },
    )
    assert r2.status_code == 409


# ---------------------------------------------------------------------------
# 5. Reschedule an appointment
# ---------------------------------------------------------------------------


def _book_one(client, auth, *, tech_id, start_hour, day):
    """Open a service call and book an appointment as a fresh customer; return (appt_id, cust_id)."""
    cust_id = auth(role=Role.CUSTOMER)
    sc = client.post(
        "/api/service-calls",
        json={"description": "Pipe fix"},
    ).json()
    book = client.post(
        "/api/appointments",
        json={
            "service_call_id": sc["id"],
            "technician_id": str(tech_id),
            "start": _utc_iso(2025, 3, day, start_hour),
            "end": _utc_iso(2025, 3, day, start_hour + 1),
        },
    ).json()
    return book["id"], cust_id


def test_reschedule_appointment_succeeds(client, auth):
    appt_id, _ = _book_one(client, auth, tech_id=uuid.uuid4(), start_hour=9, day=2)
    reschedule_resp = client.post(
        f"/api/appointments/{appt_id}/reschedule",
        json={"start": _utc_iso(2025, 3, 3, 9), "end": _utc_iso(2025, 3, 3, 11)},
    )
    assert reschedule_resp.status_code == 200
    data = reschedule_resp.json()
    assert data["status"] == "RESCHEDULED"
    assert data["id"] == appt_id


def test_reschedule_by_non_participant_returns_403(client, auth):
    """Only the appointment's customer or technician may mutate it."""
    appt_id, _ = _book_one(client, auth, tech_id=uuid.uuid4(), start_hour=14, day=10)
    # Switch to an unrelated user.
    auth(user_id=uuid.uuid4(), role=Role.CUSTOMER)
    resp = client.post(
        f"/api/appointments/{appt_id}/reschedule",
        json={"start": _utc_iso(2025, 3, 11, 9), "end": _utc_iso(2025, 3, 11, 10)},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 6. Cancel an appointment
# ---------------------------------------------------------------------------


def test_cancel_appointment_succeeds(client, auth):
    cust_id = auth(role=Role.CUSTOMER)
    sc = client.post(
        "/api/service-calls",
        json={"description": "Window seal"},
    ).json()
    tech_id = uuid.uuid4()
    book = client.post(
        "/api/appointments",
        json={
            "service_call_id": sc["id"],
            "technician_id": str(tech_id),
            "start": _utc_iso(2025, 4, 6, 14),
            "end": _utc_iso(2025, 4, 6, 15),
        },
    ).json()

    cancel_resp = client.post(f"/api/appointments/{book['id']}/cancel")
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "CANCELLED"


# ---------------------------------------------------------------------------
# 7. Add details
# ---------------------------------------------------------------------------


def test_add_details_succeeds(client, auth):
    auth(role=Role.CUSTOMER)
    sc = client.post(
        "/api/service-calls",
        json={"description": "Leaky tap"},
    ).json()
    tech_id = uuid.uuid4()
    book = client.post(
        "/api/appointments",
        json={
            "service_call_id": sc["id"],
            "technician_id": str(tech_id),
            "start": _utc_iso(2025, 5, 4, 10),
            "end": _utc_iso(2025, 5, 4, 11),
        },
    ).json()

    details_resp = client.post(
        f"/api/appointments/{book['id']}/details",
        json={"text": "Bring 3/4 inch wrench"},
    )
    assert details_resp.status_code == 200
    assert details_resp.json()["details"] == "Bring 3/4 inch wrench"


# ---------------------------------------------------------------------------
# 8. Technician self-service authorization
# ---------------------------------------------------------------------------


def test_technician_sets_own_working_hours_but_not_anothers(client, auth):
    tech_id = auth(role=Role.TECHNICIAN)
    payload = {"windows": [{"weekday": 0, "start": "09:00:00", "end": "17:00:00"}]}

    own = client.put(f"/api/technicians/{tech_id}/working-hours", json=payload)
    assert own.status_code == 200

    other = client.put(f"/api/technicians/{uuid.uuid4()}/working-hours", json=payload)
    assert other.status_code == 403


def test_customer_cannot_set_working_hours_returns_403(client, auth):
    auth(role=Role.CUSTOMER)
    resp = client.put(
        f"/api/technicians/{uuid.uuid4()}/working-hours",
        json={"windows": [{"weekday": 0, "start": "09:00:00", "end": "17:00:00"}]},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_book_against_missing_service_call_returns_404(client, auth):
    auth(role=Role.CUSTOMER)
    response = client.post(
        "/api/appointments",
        json={
            "service_call_id": str(uuid.uuid4()),
            "technician_id": str(uuid.uuid4()),
            "start": _utc_iso(2025, 6, 1, 9),
            "end": _utc_iso(2025, 6, 1, 10),
        },
    )
    assert response.status_code == 404


def test_reschedule_missing_appointment_returns_404(client, auth):
    auth(role=Role.CUSTOMER)
    response = client.post(
        f"/api/appointments/{uuid.uuid4()}/reschedule",
        json={"start": _utc_iso(2025, 6, 1, 9), "end": _utc_iso(2025, 6, 1, 10)},
    )
    assert response.status_code == 404
