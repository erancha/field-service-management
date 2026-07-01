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


def test_smtp_credentials_bind_conventional_env_names(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/fsm")
    monkeypatch.setenv("SMTP_USER", "ops@acme.com")
    monkeypatch.setenv("SMTP_PASS", "app-password")

    settings = Settings(_env_file=None)

    assert settings.smtp_username == "ops@acme.com"
    assert settings.smtp_password.get_secret_value() == "app-password"


def test_smtp_sender_address_defaults_to_account(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/fsm")
    monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setenv("SMTP_USER", "ops@acme.com")

    settings = Settings(_env_file=None)

    assert settings.smtp_sender_address == "ops@acme.com"


def test_smtp_from_overrides_sender_address(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/fsm")
    monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setenv("SMTP_USER", "ops@acme.com")
    monkeypatch.setenv("SMTP_FROM", "noreply@acme.com")

    settings = Settings(_env_file=None)

    assert settings.smtp_sender_address == "noreply@acme.com"


def test_smtp_sender_address_none_without_account(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/fsm")
    monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")

    settings = Settings(_env_file=None)

    assert settings.smtp_sender_address is None
