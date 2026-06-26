import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session
from testcontainers.postgres import PostgresContainer

from fsm.platform.app import create_app
from fsm.platform.config import Settings
from fsm.platform.db import create_engine_from_settings, session_factory


def test_health_endpoint_returns_ok():
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_landing_page_reflects_the_configured_role(monkeypatch):
    monkeypatch.setenv("FSM_ROLE", "technician")
    client = TestClient(create_app())

    response = client.get("/")

    assert response.status_code == 200
    assert "technician" in response.text


@pytest.fixture(scope="module")
def real_session_factory():
    with PostgresContainer("postgres:16", driver="psycopg") as postgres:
        settings = Settings(database_url=postgres.get_connection_url(), app_env="test")
        engine = create_engine_from_settings(settings)
        yield session_factory(engine)


def test_ready_endpoint_returns_ready_when_db_up(real_session_factory):
    client = TestClient(create_app(session_factory=real_session_factory))

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_ready_endpoint_returns_503_when_db_fails():
    def broken_factory():
        raise RuntimeError("DB unavailable")

    client = TestClient(create_app(session_factory=broken_factory))

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "not ready"}
