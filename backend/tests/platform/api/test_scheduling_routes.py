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
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from testcontainers.postgres import PostgresContainer

from fsm.assist.ports.chat_model import TriageSummary
from fsm.assist.ports.photo_store import object_prefix, original_key, preview_key
from fsm.platform.app import create_app
from fsm.identity.domain.role import Role
from tests.assist.fakes import FakePhotoStore


# ---------------------------------------------------------------------------
# Module-scoped container + migrated engine
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pg_session_factory():
    """Start a Postgres 16 container, run migrations, yield a session factory."""
    with PostgresContainer("pgvector/pgvector:pg16", driver="psycopg") as pg:
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


def _seed_user(pg_session_factory, uid, role, *, role_status="APPROVED", address=None, phone=None):
    """Insert (or update) a UserRow with the given role, approval status, and contact fields.

    These integration tests authenticate via a dependency override that creates no identity row,
    so any test whose endpoint reads the identity table seeds the referenced users here first.
    """
    from fsm.identity.adapters.orm import UserRow

    with pg_session_factory() as session:
        with session.begin():
            row = session.get(UserRow, uid)
            if row is None:
                session.add(UserRow(
                    id=uid,
                    google_sub=f"sub-{uid}",
                    email=f"{uid}@example.com",
                    name="Test User",
                    role=role.value,
                    role_status=role_status,
                    address=address,
                    phone=phone,
                ))
            else:
                row.role = role.value
                row.role_status = role_status
                row.address = address
                row.phone = phone


def _seed_contact(pg_session_factory, cust_id, tech_id, address="12 Main St", phone="+972-50-100"):
    """Seed the booking pair: a customer with address+phone and an APPROVED technician with a phone.

    Booking requires complete contact data and an approved-technician target, so tests that book
    to success seed both rows here first.
    """
    _seed_user(pg_session_factory, cust_id, Role.CUSTOMER, address=address, phone=phone)
    _seed_user(pg_session_factory, tech_id, Role.TECHNICIAN, address=address, phone=phone)


def _seed_service_call(pg_session_factory, sc_id, customer_id, description="Fix boiler",
                       triage_summary=None, headline=None):
    from fsm.scheduling.adapters.orm import ServiceCallRow
    with pg_session_factory() as s:
        with s.begin():
            s.add(ServiceCallRow(id=sc_id, customer_id=customer_id, description=description,
                                 status="OPEN", created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                                 triage_summary=triage_summary, headline=headline))


def _seed_appt(pg_session_factory, *, appt_id, sc_id, technician_id, customer_id, start, end, status="SCHEDULED"):
    from fsm.scheduling.adapters.orm import AppointmentRow
    ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
    with pg_session_factory() as s:
        with s.begin():
            s.add(AppointmentRow(id=appt_id, service_call_id=sc_id, technician_id=technician_id,
                                 customer_id=customer_id, start_at=start, end_at=end, status=status,
                                 details=None, external_event_id=None, created_at=ts, updated_at=ts))


def _seed_attachment(pg_session_factory, *, attachment_id, sc_id, object_key,
                      filename="plate.jpg", media_type="image/jpeg", size_bytes=14):
    from fsm.scheduling.adapters.orm import ServiceCallAttachmentRow
    with pg_session_factory() as s:
        with s.begin():
            s.add(ServiceCallAttachmentRow(
                id=attachment_id, service_call_id=sc_id, filename=filename, media_type=media_type,
                size_bytes=size_bytes, object_key=object_key,
                created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            ))


# ---------------------------------------------------------------------------
# Photo download fixtures
# ---------------------------------------------------------------------------


@dataclass
class PhotoSeed:
    call_id: uuid.UUID
    photo_id: uuid.UUID
    customer_id: uuid.UUID
    technician_id: uuid.UUID
    object_key: str


def _seed_photo_scenario(pg_session_factory, *, customer_id, technician_id, call_id, photo_id, object_key):
    """Seed a service call, its photo attachment, and a booked appointment for the technician."""
    _seed_user(pg_session_factory, customer_id, Role.CUSTOMER)
    _seed_user(pg_session_factory, technician_id, Role.TECHNICIAN)
    _seed_service_call(pg_session_factory, call_id, customer_id, description="Fix boiler")
    _seed_attachment(pg_session_factory, attachment_id=photo_id, sc_id=call_id, object_key=object_key)
    _seed_appt(
        pg_session_factory, appt_id=uuid.uuid4(), sc_id=call_id,
        technician_id=technician_id, customer_id=customer_id,
        start=datetime(2099, 1, 1, 9, tzinfo=timezone.utc),
        end=datetime(2099, 1, 1, 10, tzinfo=timezone.utc),
    )


@pytest.fixture
def photo_store(app):
    """Stamp a FakePhotoStore on the app's photo_store slot for one test; restore None after.

    The module-scoped app builds photo_store from unconfigured test settings, which resolves to
    None (see build_photo_store), so tests that need a working store attach one here and every
    other test keeps observing the disabled-feature default.
    """
    store = FakePhotoStore()
    app.state.photo_store = store
    yield store
    app.state.photo_store = None


@pytest.fixture
def seed(pg_session_factory, photo_store) -> PhotoSeed:
    """A service call with one photo attachment, its bytes in the store, and a booked technician."""
    customer_id, technician_id, call_id, photo_id = (uuid.uuid4() for _ in range(4))
    object_key = object_prefix(photo_id)
    _seed_photo_scenario(
        pg_session_factory, customer_id=customer_id, technician_id=technician_id,
        call_id=call_id, photo_id=photo_id, object_key=object_key,
    )
    photo_store.put(original_key(object_key), b"original-bytes", "image/jpeg")
    photo_store.put(preview_key(object_key), b"preview-bytes", "image/jpeg")
    return PhotoSeed(
        call_id=call_id, photo_id=photo_id, customer_id=customer_id,
        technician_id=technician_id, object_key=object_key,
    )


@pytest.fixture
def client_as_technician(client, auth, seed):
    auth(user_id=seed.technician_id, role=Role.TECHNICIAN)
    return client


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


def test_open_service_call_rejects_blank_description(client, auth):
    """The problem description feeds every rendering surface, so a blank one is a 422."""
    auth(role=Role.CUSTOMER)
    for description in ("", "   \n\t"):
        response = client.post("/api/service-calls", json={"description": description})
        assert response.status_code == 422


def test_open_service_call_stores_the_stripped_description(client, auth):
    auth(role=Role.CUSTOMER)
    response = client.post("/api/service-calls", json={"description": "  No hot water  "})
    assert response.status_code == 201
    assert response.json()["description"] == "No hot water"


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


def test_availability_excludes_slots_that_begin_before_now(client, auth, monkeypatch):
    """The endpoint drops slots whose start is before the current time.

    Freezes the availability clock to 12:30 UTC on a working Monday. Slots are generated and
    rendered in the service-region zone Asia/Jerusalem (UTC+2 in January), where 12:30 UTC is
    14:30 local, so only the 15:00 and 16:00 local slots of the default 09:00–17:00 schedule
    start at or after now.
    """
    from fsm.platform.api import scheduling_routes

    monkeypatch.setattr(
        scheduling_routes,
        "_now_utc",
        lambda: datetime(2025, 1, 6, 12, 30, tzinfo=timezone.utc),
    )
    auth()
    tech_id = uuid.uuid4()
    response = client.get(
        "/api/availability",
        params={
            "technician_id": str(tech_id),
            "date_from": "2025-01-06",  # Monday (default working day)
            "date_to": "2025-01-06",
            "slot_minutes": 60,
        },
    )
    assert response.status_code == 200
    slot_hours = [int(s["start"][11:13]) for s in response.json()["slots"]]
    assert slot_hours == [15, 16]


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
        },
    )
    assert response.status_code == 200
    assert response.json()["slots"] == []


def test_availability_corrupt_working_hours_falls_back_and_logs(
    client, auth, pg_session_factory, caplog
):
    """A stored working-hours row that fails domain validation (start >= end) degrades to
    the default schedule, and the degradation is logged so it isn't mistaken for the
    technician's own configured hours.
    """
    from datetime import time

    from fsm.scheduling.adapters.orm import WorkingHoursRow

    auth()
    tech_id = uuid.uuid4()
    with pg_session_factory() as session:
        with session.begin():
            # weekday=6 is Sunday; start >= end violates DailyHours' invariant.
            session.add(
                WorkingHoursRow(
                    technician_id=tech_id, weekday=6, start_time=time(17, 0), end_time=time(9, 0)
                )
            )

    with caplog.at_level("WARNING", logger="fsm.platform.api.scheduling_routes"):
        response = client.get(
            "/api/availability",
            params={
                "technician_id": str(tech_id),
                "date_from": "2025-01-05",  # Sunday
                "date_to": "2025-01-05",
                "slot_minutes": 60,
            },
        )
    assert response.status_code == 200
    # Falls back to WeeklyWorkingHours.default(): Sun 09:00-17:00 = 8 one-hour slots.
    assert len(response.json()["slots"]) == 8
    assert str(tech_id) in caplog.text


def test_availability_unexpected_working_hours_error_propagates(client, auth, monkeypatch):
    """Only a SchedulingError from parsing stored working hours is degraded; any other
    error reading them must surface rather than being absorbed into the default schedule.
    """
    from fsm.scheduling.adapters.working_hours_repository import SqlAlchemyWorkingHoursRepository

    def _boom(self, technician_id):
        raise RuntimeError("working hours store unavailable")

    monkeypatch.setattr(SqlAlchemyWorkingHoursRepository, "get_for_technician", _boom)
    auth()
    with pytest.raises(RuntimeError, match="working hours store unavailable"):
        client.get(
            "/api/availability",
            params={
                "technician_id": str(uuid.uuid4()),
                "date_from": "2025-01-05",
                "date_to": "2025-01-05",
            },
        )


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
    _seed_contact(pg_session_factory, cust_id, tech_id)
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


def test_book_without_required_contact_returns_422(client, auth, pg_session_factory):
    """Booking is refused when the customer/technician contact data is incomplete."""
    auth(role=Role.CUSTOMER)
    # An approved technician without a phone: the booking passes the technician gate and fails
    # on the contact-completeness contract for both parties (the customer has no row at all).
    tech_id = uuid.uuid4()
    _seed_user(pg_session_factory, tech_id, Role.TECHNICIAN)
    sc_id = client.post("/api/service-calls", json={"description": "No contact yet"}).json()["id"]

    resp = client.post(
        "/api/appointments",
        json={
            "service_call_id": sc_id,
            "technician_id": str(tech_id),
            "start": _utc_iso(2025, 3, 4, 9),
            "end": _utc_iso(2025, 3, 4, 10),
        },
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "customer phone" in detail and "technician phone" in detail


def test_book_non_approved_technician_returns_404(client, auth, pg_session_factory):
    """The booking target must be an APPROVED technician (issue #14).

    A technician still pending approval and an id with no user at all are both rejected as
    nonexistent bookable technicians, so the admin approval queue cannot be bypassed by
    booking a connected-but-unapproved user directly.
    """
    cust_id = auth(role=Role.CUSTOMER)
    _seed_user(pg_session_factory, cust_id, Role.CUSTOMER, address="12 Main St", phone="+972-50-100")
    pending_tech = uuid.uuid4()
    _seed_user(
        pg_session_factory, pending_tech, Role.TECHNICIAN, role_status="PENDING", phone="+972-50-100"
    )
    sc_id = client.post("/api/service-calls", json={"description": "Bypass attempt"}).json()["id"]

    for target in (pending_tech, uuid.uuid4()):
        resp = client.post(
            "/api/appointments",
            json={
                "service_call_id": sc_id,
                "technician_id": str(target),
                "start": _utc_iso(2025, 4, 6, 9),
                "end": _utc_iso(2025, 4, 6, 10),
            },
        )
        assert resp.status_code == 404
        assert "technician" in resp.json()["detail"].lower()


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


def test_booking_overlapping_slot_returns_409(client, auth, pg_session_factory):
    cust_id = auth(role=Role.CUSTOMER)
    tech_id = uuid.uuid4()
    _seed_contact(pg_session_factory, cust_id, tech_id)

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


def _book_one(client, auth, pg_session_factory, *, tech_id, start_hour, day):
    """Open a service call and book an appointment as a fresh customer; return (appt_id, cust_id)."""
    cust_id = auth(role=Role.CUSTOMER)
    _seed_contact(pg_session_factory, cust_id, tech_id)
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


def test_reschedule_appointment_succeeds(client, auth, pg_session_factory):
    appt_id, _ = _book_one(client, auth, pg_session_factory, tech_id=uuid.uuid4(), start_hour=9, day=2)
    reschedule_resp = client.post(
        f"/api/appointments/{appt_id}/reschedule",
        json={"start": _utc_iso(2025, 3, 3, 9), "end": _utc_iso(2025, 3, 3, 11)},
    )
    assert reschedule_resp.status_code == 200
    data = reschedule_resp.json()
    assert data["status"] == "RESCHEDULED"
    assert data["id"] == appt_id


def test_reschedule_by_non_participant_returns_403(client, auth, pg_session_factory):
    """Only the appointment's customer or technician may mutate it."""
    appt_id, _ = _book_one(client, auth, pg_session_factory, tech_id=uuid.uuid4(), start_hour=14, day=10)
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


def test_cancel_appointment_succeeds(client, auth, pg_session_factory):
    cust_id = auth(role=Role.CUSTOMER)
    tech_id = uuid.uuid4()
    _seed_contact(pg_session_factory, cust_id, tech_id)
    sc = client.post(
        "/api/service-calls",
        json={"description": "Window seal"},
    ).json()
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


def test_add_details_succeeds(client, auth, pg_session_factory):
    cust_id = auth(role=Role.CUSTOMER)
    tech_id = uuid.uuid4()
    _seed_contact(pg_session_factory, cust_id, tech_id)
    sc = client.post(
        "/api/service-calls",
        json={"description": "Leaky tap"},
    ).json()
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


def test_reschedule_incomplete_contact_info_returns_422(client, auth, pg_session_factory, monkeypatch):
    """Domain errors are mapped app-wide, so IncompleteContactInfo is a 422 on every endpoint,
    not just on booking."""
    from fsm.scheduling.application.appointment_service import AppointmentService
    from fsm.scheduling.domain.errors import IncompleteContactInfo

    appt_id, _ = _book_one(client, auth, pg_session_factory, tech_id=uuid.uuid4(), start_hour=9, day=17)

    def _raise(self, **kwargs):
        raise IncompleteContactInfo(["customer phone"])

    monkeypatch.setattr(AppointmentService, "reschedule_appointment", _raise)
    response = client.post(
        f"/api/appointments/{appt_id}/reschedule",
        json={"start": _utc_iso(2025, 3, 18, 9), "end": _utc_iso(2025, 3, 18, 10)},
    )
    assert response.status_code == 422
    assert "customer phone" in response.json()["detail"]


class TestUpcomingEndpoint:
    def _far(self, day, hour=9):
        return datetime(2099, 6, day, hour, tzinfo=timezone.utc)

    def test_technician_sees_own_upcoming_sorted_and_enriched(self, client, auth, pg_session_factory):
        tech = uuid.uuid4()
        cust = uuid.uuid4()
        _seed_user(pg_session_factory, tech, Role.TECHNICIAN)
        _seed_user(pg_session_factory, cust, Role.CUSTOMER, address="12 Main St")
        sc = uuid.uuid4()
        _seed_service_call(pg_session_factory, sc, cust, description="Fix boiler")
        later, sooner = uuid.uuid4(), uuid.uuid4()
        _seed_appt(pg_session_factory, appt_id=later, sc_id=sc, technician_id=tech, customer_id=cust, start=self._far(2), end=self._far(2, 11))
        _seed_appt(pg_session_factory, appt_id=sooner, sc_id=sc, technician_id=tech, customer_id=cust, start=self._far(1), end=self._far(1, 11))
        _seed_appt(pg_session_factory, appt_id=uuid.uuid4(), sc_id=sc, technician_id=tech, customer_id=cust, start=self._far(3), end=self._far(3, 11), status="CANCELLED")
        _seed_appt(pg_session_factory, appt_id=uuid.uuid4(), sc_id=sc, technician_id=tech, customer_id=cust,
                   start=datetime(2000, 1, 1, 9, tzinfo=timezone.utc), end=datetime(2000, 1, 1, 11, tzinfo=timezone.utc))

        auth(user_id=tech, role=Role.TECHNICIAN)
        resp = client.get("/api/appointments/upcoming", params={"limit": 5})

        assert resp.status_code == 200
        items = resp.json()["items"]
        assert [i["id"] for i in items] == [str(sooner), str(later)]
        assert items[0]["problem"] == "Fix boiler"
        assert items[0]["technician_name"] == "Test User"
        assert items[0]["customer_name"] == "Test User"
        assert items[0]["address"] == "12 Main St"
        assert items[0]["created_at"].startswith("2024-01-01")

    def test_scope_is_per_role(self, client, auth, pg_session_factory):
        tech = uuid.uuid4()
        cust = uuid.uuid4()
        other_cust = uuid.uuid4()
        for u, r in [(tech, Role.TECHNICIAN), (cust, Role.CUSTOMER), (other_cust, Role.CUSTOMER)]:
            _seed_user(pg_session_factory, u, r)
        sc = uuid.uuid4()
        _seed_service_call(pg_session_factory, sc, cust)
        mine, theirs = uuid.uuid4(), uuid.uuid4()
        _seed_appt(pg_session_factory, appt_id=mine, sc_id=sc, technician_id=tech, customer_id=cust, start=self._far(1), end=self._far(1, 11))
        _seed_appt(pg_session_factory, appt_id=theirs, sc_id=sc, technician_id=tech, customer_id=other_cust, start=self._far(2), end=self._far(2, 11))

        auth(user_id=cust, role=Role.CUSTOMER)
        customer_ids = {i["id"] for i in client.get("/api/appointments/upcoming", params={"limit": 3}).json()["items"]}
        assert str(mine) in customer_ids and str(theirs) not in customer_ids

        auth(user_id=uuid.uuid4(), role=Role.ADMIN)
        admin_ids = {i["id"] for i in client.get("/api/appointments/upcoming", params={"limit": 10}).json()["items"]}
        assert {str(mine), str(theirs)} <= admin_ids

    def test_upcoming_appointments_carry_the_calls_photo_list(self, client_as_technician, seed):
        items = client_as_technician.get("/api/appointments/upcoming", params={"limit": 5}).json()["items"]

        assert items[0]["photos"] == [
            {"id": str(seed.photo_id), "filename": "plate.jpg", "size_bytes": 14}
        ]

    def test_an_escalated_call_ships_the_layout_so_the_client_renders_no_prose(
        self, client, auth, pg_session_factory
    ):
        summary = TriageSummary(
            equipment="LG 86NANO91VPA television",
            problem_category="No picture, sound present",
            symptoms="Sound plays normally",
            suspected_cause="Backlight failure",
            action_items=("Bring backlight strip parts",),
            steps_ruled_out=("Flashlight test showed no faint image",),
        )
        tech, cust, sc = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        _seed_user(pg_session_factory, tech, Role.TECHNICIAN)
        _seed_user(pg_session_factory, cust, Role.CUSTOMER)
        _seed_service_call(pg_session_factory, sc, cust, description=summary.render(),
                           triage_summary=summary.as_dict(), headline=summary.headline())
        _seed_appt(pg_session_factory, appt_id=uuid.uuid4(), sc_id=sc, technician_id=tech,
                   customer_id=cust, start=self._far(1), end=self._far(1, 11))
        auth(tech, Role.TECHNICIAN)

        [item] = client.get("/api/appointments/upcoming", params={"limit": 5}).json()["items"]

        assert item["headline"] == "No picture, sound present"
        assert [block["heading"] for block in item["summary"]] == [
            "Problem",
            "Action items",
            "Triage summary",
            "Steps ruled out",
        ]
        assert item["summary"][0] == {
            "heading": "Problem",
            "bullets": ["No picture, sound present", "Sound plays normally"],
            "fields": [],
        }
        assert item["summary"][2]["fields"] == [
            ["Equipment", "LG 86NANO91VPA television"],
            ["Suspected cause", "Backlight failure"],
        ]

    def test_a_call_opened_from_the_description_form_ships_its_first_line_as_the_headline(
        self, client, auth, pg_session_factory
    ):
        tech, cust, sc = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        _seed_user(pg_session_factory, tech, Role.TECHNICIAN)
        _seed_user(pg_session_factory, cust, Role.CUSTOMER)
        _seed_service_call(pg_session_factory, sc, cust, description="Boiler leaks\nSee the photo")
        _seed_appt(pg_session_factory, appt_id=uuid.uuid4(), sc_id=sc, technician_id=tech,
                   customer_id=cust, start=self._far(1), end=self._far(1, 11))
        auth(tech, Role.TECHNICIAN)

        [item] = client.get("/api/appointments/upcoming", params={"limit": 5}).json()["items"]

        assert item["summary"] is None
        assert item["headline"] == "Boiler leaks"
        assert item["problem"] == "Boiler leaks\nSee the photo"

    def test_upcoming_appointments_photos_default_to_empty(self, client, auth, pg_session_factory):
        """A call with no attachment rows renders an empty photo list, not an omitted field."""
        tech = uuid.uuid4()
        cust = uuid.uuid4()
        _seed_user(pg_session_factory, tech, Role.TECHNICIAN)
        _seed_user(pg_session_factory, cust, Role.CUSTOMER)
        sc = uuid.uuid4()
        _seed_service_call(pg_session_factory, sc, cust)
        _seed_appt(pg_session_factory, appt_id=uuid.uuid4(), sc_id=sc, technician_id=tech, customer_id=cust,
                   start=self._far(1), end=self._far(1, 11))

        auth(user_id=tech, role=Role.TECHNICIAN)
        items = client.get("/api/appointments/upcoming", params={"limit": 5}).json()["items"]
        assert items[0]["photos"] == []


# ---------------------------------------------------------------------------
# 9. Service-call photo download
# ---------------------------------------------------------------------------


class TestServiceCallPhotoDownload:
    def test_technician_on_the_appointment_gets_the_original_shown_inline(
        self, client_as_technician, seed
    ):
        """The original is served inline so a calendar link or web thumbnail click displays the
        image in the browser; the filename in the header still names a save-as."""
        response = client_as_technician.get(
            f"/api/service-calls/{seed.call_id}/photos/{seed.photo_id}"
        )

        assert response.status_code == 200
        assert response.content == b"original-bytes"
        assert response.headers["content-type"].startswith("image/jpeg")
        assert response.headers["content-disposition"] == (
            'inline; filename="plate.jpg"; filename*=UTF-8\'\'plate.jpg'
        )

    def test_preview_variant_serves_the_inline_jpeg(self, client_as_technician, seed):
        response = client_as_technician.get(
            f"/api/service-calls/{seed.call_id}/photos/{seed.photo_id}",
            params={"variant": "preview"},
        )

        assert response.status_code == 200
        assert response.content == b"preview-bytes"
        assert response.headers["content-disposition"].startswith("inline")

    def test_the_calls_customer_and_an_admin_may_download(self, client, auth, seed):
        auth(user_id=seed.customer_id, role=Role.CUSTOMER)
        customer_resp = client.get(f"/api/service-calls/{seed.call_id}/photos/{seed.photo_id}")
        assert customer_resp.status_code == 200

        auth(user_id=uuid.uuid4(), role=Role.ADMIN)
        admin_resp = client.get(f"/api/service-calls/{seed.call_id}/photos/{seed.photo_id}")
        assert admin_resp.status_code == 200

    def test_an_unrelated_technician_is_403(self, client, auth, seed):
        auth(user_id=uuid.uuid4(), role=Role.TECHNICIAN)
        response = client.get(f"/api/service-calls/{seed.call_id}/photos/{seed.photo_id}")
        assert response.status_code == 403

    def test_an_unrelated_customer_is_403(self, client, auth, seed):
        auth(user_id=uuid.uuid4(), role=Role.CUSTOMER)
        response = client.get(f"/api/service-calls/{seed.call_id}/photos/{seed.photo_id}")
        assert response.status_code == 403

    def test_unknown_photo_id_returns_404(self, client_as_technician, seed):
        response = client_as_technician.get(
            f"/api/service-calls/{seed.call_id}/photos/{uuid.uuid4()}"
        )
        assert response.status_code == 404

    def test_photo_belonging_to_another_service_call_returns_404(
        self, client_as_technician, seed, pg_session_factory, photo_store
    ):
        other_customer, other_call, other_photo = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        _seed_service_call(pg_session_factory, other_call, other_customer, description="Other call")
        _seed_attachment(
            pg_session_factory, attachment_id=other_photo, sc_id=other_call,
            object_key=object_prefix(other_photo),
        )

        response = client_as_technician.get(
            f"/api/service-calls/{seed.call_id}/photos/{other_photo}"
        )
        assert response.status_code == 404

    def test_non_ascii_filename_downloads_with_rfc5987_header(
        self, client_as_technician, seed, pg_session_factory, photo_store
    ):
        """A customer-supplied non-ASCII filename must not crash Content-Disposition encoding:
        Starlette serializes response headers as latin-1, so the raw filename can never be
        interpolated as-is."""
        photo_id = uuid.uuid4()
        object_key = object_prefix(photo_id)
        _seed_attachment(
            pg_session_factory, attachment_id=photo_id, sc_id=seed.call_id,
            object_key=object_key, filename="צילום-דוד.jpg",
        )
        photo_store.put(original_key(object_key), b"original-bytes", "image/jpeg")
        photo_store.put(preview_key(object_key), b"preview-bytes", "image/jpeg")

        for params in ({}, {"variant": "preview"}):
            response = client_as_technician.get(
                f"/api/service-calls/{seed.call_id}/photos/{photo_id}", params=params
            )
            assert response.status_code == 200
            header = response.headers["content-disposition"]
            header.encode("latin-1")  # raises if a raw non-ASCII byte leaked into the header
            assert "filename*=UTF-8''%D7%A6%D7%99%D7%9C%D7%95%D7%9D" in header
            ascii_fallback = header.split('filename="', 1)[1].split('"', 1)[0]
            assert ascii_fallback.isascii()

    def test_download_without_configured_store_returns_503(self, client, auth, pg_session_factory):
        customer_id, technician_id, call_id, photo_id = (uuid.uuid4() for _ in range(4))
        _seed_photo_scenario(
            pg_session_factory, customer_id=customer_id, technician_id=technician_id,
            call_id=call_id, photo_id=photo_id, object_key=object_prefix(photo_id),
        )
        auth(user_id=customer_id, role=Role.CUSTOMER)

        response = client.get(f"/api/service-calls/{call_id}/photos/{photo_id}")

        assert response.status_code == 503
        assert response.json()["detail"] == "Photo storage not configured"


class TestAppointmentChangePublish:
    def test_cancel_publishes_change_to_both_participants(self, client, auth, pg_session_factory, monkeypatch):
        from fsm.platform.api import scheduling_routes

        tech = uuid.uuid4()
        cust = uuid.uuid4()
        _seed_user(pg_session_factory, tech, Role.TECHNICIAN)
        _seed_user(pg_session_factory, cust, Role.CUSTOMER, address="12 Main St")
        sc = uuid.uuid4()
        _seed_service_call(pg_session_factory, sc, cust)
        appt_id = uuid.uuid4()
        _seed_appt(pg_session_factory, appt_id=appt_id, sc_id=sc, technician_id=tech, customer_id=cust,
                   start=datetime(2099, 6, 1, 9, tzinfo=timezone.utc), end=datetime(2099, 6, 1, 11, tzinfo=timezone.utc))

        calls = []
        monkeypatch.setattr(scheduling_routes, "publish_appointment_changed",
                            lambda app, **kw: calls.append(kw))

        auth(user_id=cust, role=Role.CUSTOMER)
        resp = client.post(f"/api/appointments/{appt_id}/cancel")

        assert resp.status_code == 200
        assert calls == [{"appointment_id": appt_id, "customer_id": cust, "technician_id": tech}]
