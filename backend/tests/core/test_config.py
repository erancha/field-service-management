from fsm.core.config import CoreSettings


def test_settings_read_from_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/db")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

    settings = CoreSettings(_env_file=None)

    assert settings.database_url.get_secret_value() == "postgresql+psycopg://u:p@localhost:5432/db"
    assert settings.app_env == "test"
    assert settings.redis_url == "redis://localhost:6379/0"


def test_unknown_keys_are_ignored(monkeypatch):
    """One environment serves several processes, so a key another process owns is not an error."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/db")
    monkeypatch.setenv("SOME_OTHER_PROCESS_SETTING", "x")

    assert CoreSettings(_env_file=None).app_env == "local"
