import warnings

import pytest
from fastapi.testclient import TestClient
from testcontainers.postgres import PostgresContainer

from fsm.core.db import session_factory
from fsm.platform.app import create_app
from fsm.platform.config import Settings
from fsm.platform.db import create_engine_from_settings


def test_health_endpoint_returns_ok():
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def _settings(**overrides) -> Settings:
    values: dict = dict(
        database_url="postgresql+psycopg://fsm:fsm@localhost:5432/fsm",
        app_env="test",
        fsm_role="technician",
    )
    values.update(overrides)
    return Settings(**values)


def test_landing_page_reflects_the_configured_role():
    client = TestClient(create_app(settings=_settings(fsm_role="customer")))

    response = client.get("/")

    assert response.status_code == 200
    assert "customer" in response.text


def test_role_comes_from_the_settings_not_the_process_environment(monkeypatch):
    """Injected settings are the single source of the role, so the two readers cannot disagree."""
    monkeypatch.setenv("FSM_ROLE", "backoffice")

    app = create_app(settings=_settings(fsm_role="technician"))

    assert "technician" in app.title


def test_create_app_refuses_a_misspelled_role():
    """Serving with an unrecognized role would sign every user in through the customer funnel."""
    with pytest.raises(ValueError, match="FSM_ROLE"):
        create_app(settings=_settings(fsm_role="backofice"))


def test_create_app_refuses_a_process_with_no_role_configured():
    with pytest.raises(ValueError, match="FSM_ROLE"):
        create_app(settings=_settings(fsm_role="unknown"))


def _settings_with_session(app_env: str) -> Settings:
    return _settings(app_env=app_env, session_secret="test-session-secret-32-bytes-long!!")


@pytest.mark.parametrize("app_env", ["staging", "prod"])
def test_session_cookie_is_secure_outside_local_and_test(app_env):
    app = create_app(settings=_settings_with_session(app_env))

    (middleware,) = app.user_middleware
    assert middleware.kwargs["https_only"] is True


@pytest.mark.parametrize("app_env", ["local", "test"])
def test_session_cookie_is_not_secure_for_local_and_test(app_env):
    app = create_app(settings=_settings_with_session(app_env))

    (middleware,) = app.user_middleware
    assert middleware.kwargs["https_only"] is False


def test_no_serving_role_runs_a_background_loop():
    """The loops belong to the worker deployment, so scaling any HTTP role duplicates nothing."""
    from fsm.platform.roles import DEPLOYMENTS, SERVING_ROLES, Worker

    assert [DEPLOYMENTS[role].workers for role in SERVING_ROLES] == [(), (), ()]
    assert DEPLOYMENTS["worker"].workers == (Worker.CALENDAR_DISPATCH, Worker.INBOUND_SYNC)
    assert "worker" not in SERVING_ROLES


def test_create_app_emits_no_deprecation_warnings():
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        create_app(session_factory=lambda: None, settings=_settings())


@pytest.fixture(scope="module")
def real_session_factory():
    with PostgresContainer("pgvector/pgvector:pg16", driver="psycopg") as postgres:
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
