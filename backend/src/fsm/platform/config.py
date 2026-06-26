"""Application configuration loaded from the environment."""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process-wide configuration. Immutable once constructed."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    database_url: SecretStr
    app_env: Literal["local", "test", "staging", "prod"] = "local"

    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None
    google_redirect_uri: str = "http://localhost:8001/auth/google/callback"
    session_secret: SecretStr | None = None

    fsm_token_key: SecretStr | None = None
    google_calendar_redirect_uri: str = "http://localhost:8001/calendar/connect/callback"

    fsm_dispatch_enabled: bool = False
    fsm_dispatch_interval_seconds: float = 5.0

    fsm_sync_enabled: bool = False
    fsm_sync_interval_seconds: float = 30.0

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from: str | None = None
    smtp_use_tls: bool = True

    google_api_key: SecretStr | None = None
    holiday_calendar_id: str | None = None
    holiday_refresh_years_ahead: int = 1

    # An optional key present but left blank in .env (e.g. `SESSION_SECRET=`) is treated as
    # unset, so an uncommented-but-empty template entry behaves the same as an absent one.
    @field_validator(
        "google_client_id",
        "google_client_secret",
        "session_secret",
        "fsm_token_key",
        "smtp_host",
        "smtp_username",
        "smtp_password",
        "smtp_from",
        "google_api_key",
        "holiday_calendar_id",
        mode="before",
    )
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if isinstance(value, str) and value.strip() == "":
            return None
        return value


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
