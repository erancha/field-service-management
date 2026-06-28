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

    # Which deployment this process serves: technician | customer | backoffice. Drives the
    # sign-in role assignment (see SignInHost) and the landing-page title.
    fsm_role: str = "unknown"
    # Comma-separated emails granted ADMIN on first back-office sign-in. The only path to ADMIN.
    admin_emails: str | None = None
    # Redis pub/sub URL backing cross-process SSE delivery. Absent in host mode (single process
    # per role), where the in-memory event bus suffices.
    redis_url: str | None = None

    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None
    # OAuth sign-in callback URL. Blank (default) derives it per request from the host the sign-in
    # began on, so each role completes OAuth on its own edge host behind nginx; set an explicit value
    # only for a fixed public deployment. Either way it must be registered on the Google OAuth client.
    google_redirect_uri: str = ""
    session_secret: SecretStr | None = None

    fsm_token_key: SecretStr | None = None
    # Calendar-connect callback URL; same blank-derives-per-host rule as google_redirect_uri.
    google_calendar_redirect_uri: str = ""

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
        "admin_emails",
        "redis_url",
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

    @property
    def admin_email_set(self) -> frozenset[str]:
        """Lower-cased administrator allowlist parsed from the comma-separated admin_emails."""
        if not self.admin_emails:
            return frozenset()
        return frozenset(
            part.strip().lower() for part in self.admin_emails.split(",") if part.strip()
        )


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
