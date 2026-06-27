"""Integration tests for the back-office approval queue and host-aware sign-in.

A Postgres 16 container is started once per module. Tests drive the real TestClient so routing,
the require_role(ADMIN) gate, the DB-resolved role, and persistence all run end-to-end. The OIDC
seams (token_exchange_override / auth_adapter_override) let the callback run per sign-in host.
"""
from __future__ import annotations

import os
import uuid
from unittest.mock import MagicMock

import pytest
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from testcontainers.postgres import PostgresContainer

from fsm.identity.adapters.repositories import SqlAlchemyUserRepository
from fsm.identity.domain.role import Role
from fsm.identity.domain.role_status import RoleStatus
from fsm.identity.domain.user import User
from fsm.identity.ports.auth import VerifiedIdentity
from fsm.platform.app import create_app
from fsm.platform.config import Settings


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
        yield sessionmaker(bind=engine, expire_on_commit=False)
        engine.dispose()
        del os.environ["DATABASE_URL"]


def _settings(pg_url: str, *, fsm_role: str = "unknown", admin_emails: str | None = None) -> Settings:
    return Settings(
        database_url=pg_url,
        app_env="test",
        fsm_role=fsm_role,
        admin_emails=admin_emails,
        google_client_id="test-client-id.apps.googleusercontent.com",
        google_client_secret="test-client-secret",
        google_redirect_uri="http://localhost:8001/auth/google/callback",
        session_secret="test-session-secret-32-bytes-long!!",
    )


def _seed_user(factory, *, role: Role, status: RoleStatus, email: str = "t@example.com") -> uuid.UUID:
    uid = uuid.uuid4()
    with factory() as session:
        SqlAlchemyUserRepository(session).add(
            User(
                id=uid,
                google_sub=f"sub-{uid}",
                email=email,
                name="Tech Person",
                role=role,
                role_status=status,
            )
        )
        session.commit()
    return uid


def _callback_through_login(client) -> None:
    from urllib.parse import parse_qs, urlparse

    login = client.get("/auth/google/login")
    state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
    client.get(f"/auth/google/callback?code=fake-code&state={state}")


def _signed_in_client(app, identity: VerifiedIdentity) -> TestClient:
    app.state.token_exchange_override = lambda flow, code: "fake-id-token"
    adapter = MagicMock()
    adapter.verify.return_value = identity
    app.state.auth_adapter_override = adapter
    return TestClient(app, follow_redirects=False)


# ---------------------------------------------------------------------------
# Back-office queue (ADMIN-gated)
# ---------------------------------------------------------------------------


class TestBackOfficeQueue:
    def test_admin_lists_pending_then_approves_and_db_reflects_it(
        self, pg_session_factory, authenticate
    ):
        app = create_app(session_factory=pg_session_factory, settings=_settings(os.environ["DATABASE_URL"]))
        client = TestClient(app, follow_redirects=False)
        pending_id = _seed_user(
            pg_session_factory, role=Role.TECHNICIAN, status=RoleStatus.PENDING, email="pend@example.com"
        )
        authenticate(app, role=Role.ADMIN)

        listed = client.get("/api/back-office/technician-requests")
        assert listed.status_code == 200
        assert str(pending_id) in [r["user_id"] for r in listed.json()]

        approved = client.post(f"/api/back-office/technician-requests/{pending_id}/approve")
        assert approved.status_code == 200
        assert approved.json()["role_status"] == "APPROVED"

        with pg_session_factory() as session:
            assert SqlAlchemyUserRepository(session).get(pending_id).role_status == RoleStatus.APPROVED

    def test_reject_sets_rejected(self, pg_session_factory, authenticate):
        app = create_app(session_factory=pg_session_factory, settings=_settings(os.environ["DATABASE_URL"]))
        client = TestClient(app, follow_redirects=False)
        pending_id = _seed_user(
            pg_session_factory, role=Role.TECHNICIAN, status=RoleStatus.PENDING, email="rej@example.com"
        )
        authenticate(app, role=Role.ADMIN)

        rejected = client.post(f"/api/back-office/technician-requests/{pending_id}/reject")
        assert rejected.status_code == 200
        assert rejected.json()["role_status"] == "REJECTED"

    def test_non_admin_is_forbidden(self, pg_session_factory, authenticate):
        app = create_app(session_factory=pg_session_factory, settings=_settings(os.environ["DATABASE_URL"]))
        client = TestClient(app, follow_redirects=False)
        authenticate(app, role=Role.CUSTOMER)
        assert client.get("/api/back-office/technician-requests").status_code == 403

    def test_approve_unknown_user_is_404(self, pg_session_factory, authenticate):
        app = create_app(session_factory=pg_session_factory, settings=_settings(os.environ["DATABASE_URL"]))
        client = TestClient(app, follow_redirects=False)
        authenticate(app, role=Role.ADMIN)
        resp = client.post(f"/api/back-office/technician-requests/{uuid.uuid4()}/approve")
        assert resp.status_code == 404

    def test_approve_non_pending_is_409(self, pg_session_factory, authenticate):
        app = create_app(session_factory=pg_session_factory, settings=_settings(os.environ["DATABASE_URL"]))
        client = TestClient(app, follow_redirects=False)
        customer_id = _seed_user(
            pg_session_factory, role=Role.CUSTOMER, status=RoleStatus.APPROVED, email="cust@example.com"
        )
        authenticate(app, role=Role.ADMIN)
        resp = client.post(f"/api/back-office/technician-requests/{customer_id}/approve")
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Host-aware sign-in via the OIDC callback
# ---------------------------------------------------------------------------


class TestHostAwareSignIn:
    def test_technician_host_sign_in_is_pending_technician(self, pg_session_factory):
        app = create_app(
            session_factory=pg_session_factory,
            settings=_settings(os.environ["DATABASE_URL"], fsm_role="technician"),
        )
        client = _signed_in_client(
            app, VerifiedIdentity("sub-tech-host", "techhost@example.com", "Tech Host")
        )
        _callback_through_login(client)

        me = client.get("/auth/me").json()
        assert me["role"] == "TECHNICIAN"
        assert me["role_status"] == "PENDING"

    def test_backoffice_host_refuses_non_allowlisted(self, pg_session_factory):
        app = create_app(
            session_factory=pg_session_factory,
            settings=_settings(os.environ["DATABASE_URL"], fsm_role="backoffice", admin_emails=""),
        )
        client = _signed_in_client(
            app, VerifiedIdentity("sub-stranger", "stranger@example.com", "Stranger")
        )
        from urllib.parse import parse_qs, urlparse

        login = client.get("/auth/google/login")
        state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
        resp = client.get(f"/auth/google/callback?code=fake-code&state={state}")
        assert resp.status_code == 403

    def test_backoffice_host_grants_admin_to_allowlisted(self, pg_session_factory):
        app = create_app(
            session_factory=pg_session_factory,
            settings=_settings(
                os.environ["DATABASE_URL"], fsm_role="backoffice", admin_emails="boss@example.com"
            ),
        )
        client = _signed_in_client(
            app, VerifiedIdentity("sub-boss-host", "boss@example.com", "Boss")
        )
        _callback_through_login(client)

        me = client.get("/auth/me").json()
        assert me["role"] == "ADMIN"
        assert me["role_status"] == "APPROVED"


# ---------------------------------------------------------------------------
# SSE endpoint gating
# ---------------------------------------------------------------------------


def test_events_stream_requires_authentication(pg_session_factory):
    app = create_app(session_factory=pg_session_factory, settings=_settings(os.environ["DATABASE_URL"]))
    client = TestClient(app, follow_redirects=False)
    assert client.get("/api/events").status_code == 401
