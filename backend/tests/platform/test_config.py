from fsm.platform.config import Settings, get_settings


def test_settings_read_from_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/fsm")
    monkeypatch.setenv("APP_ENV", "test")

    settings = Settings()

    assert settings.database_url.get_secret_value() == "postgresql+psycopg://u:p@localhost:5432/fsm"
    assert settings.app_env == "test"


def test_get_settings_is_cached(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/fsm")
    get_settings.cache_clear()

    assert get_settings() is get_settings()


def test_database_url_not_leaked_in_repr(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:supersecretpassword@localhost:5432/fsm")

    settings = Settings()

    assert "supersecretpassword" not in repr(settings)
    assert "supersecretpassword" not in str(settings)


def test_app_env_rejects_invalid_value(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/fsm")
    monkeypatch.setenv("APP_ENV", "development")

    import pytest
    with pytest.raises(Exception):
        Settings()
