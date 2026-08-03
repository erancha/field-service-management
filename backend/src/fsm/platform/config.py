"""FSM's own configuration, extending the settings any backend process needs."""

import zoneinfo
from functools import lru_cache

from pydantic import AliasChoices, Field, SecretStr, field_validator

from fsm.core.config import CoreSettings


DEFAULT_TIMEZONE = "Asia/Jerusalem"


class Settings(CoreSettings):
    """Process-wide configuration. Immutable once constructed.

    Adds this product's own fields to the database, environment, and broker settings every backend
    process needs.
    """

    # IANA zone the single service region operates in; appointment times are rendered in it.
    timezone: str = DEFAULT_TIMEZONE

    # Which deployment this process serves: technician | customer | backoffice. Drives the
    # sign-in role assignment (see SignInHost) and the landing-page title.
    fsm_role: str = "unknown"
    # Comma-separated emails granted ADMIN on first back-office sign-in. The only path to ADMIN.
    admin_emails: str | None = None

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
    # Public base URL of the technician-facing deployment (scheme + host, e.g.
    # https://tech.example.com). The calendar dispatcher builds the photo links it writes into
    # events from it — it runs outside any request, so the host cannot be derived per request.
    # None is legal only where dispatch is off; a dispatch-enabled process refuses to start
    # without it.
    technician_app_url: str | None = None

    fsm_sync_enabled: bool = False
    fsm_sync_interval_seconds: float = 30.0

    # Book/cancel churn limit: a customer who cancels fsm_booking_cancel_limit or more
    # appointments within the rolling window is blocked from booking until the cool-off
    # elapses after their latest cancellation. A limit of 0 disables the check.
    fsm_booking_cancel_limit: int = Field(default=3, ge=0)
    fsm_booking_cancel_window_hours: float = Field(default=24.0, gt=0)
    fsm_booking_cancel_cooloff_hours: float = Field(default=24.0, gt=0)

    smtp_host: str | None = None
    smtp_port: int = 587
    # Account we authenticate to the relay as. In the Gmail model this address is also the sender,
    # so smtp_sender_address defaults the From header to it. Read from the conventional SMTP_USER.
    smtp_username: str | None = Field(
        default=None, validation_alias=AliasChoices("smtp_user", "smtp_username")
    )
    # For Gmail, a 16-character App Password. Read from the conventional SMTP_PASS.
    smtp_password: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("smtp_pass", "smtp_password")
    )
    smtp_from: str | None = None
    smtp_use_tls: bool = True

    google_api_key: SecretStr | None = None
    holiday_calendar_id: str | None = None
    holiday_refresh_years_ahead: int = 1

    # AI triage assistant. provider:model strings with no in-code default — the chosen models
    # live in .env (.env.example documents them). The KB is enabled only when both an embeddings
    # model and the key matching its provider are present.
    assist_model: str | None = None
    assist_embeddings: str | None = None
    anthropic_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None

    # Object storage for customer photos from the triage chat. Defaults match the bundled
    # docker-compose MinIO service, the same way DATABASE_URL defaults to the bundled Postgres.
    # Only the photo feature reads these; with the triage chat disabled they are ignored.
    minio_endpoint: str = "localhost:9100"
    minio_access_key: str = "fsm"
    minio_secret_key: SecretStr = SecretStr("fsm-minio-local")
    minio_bucket: str = "fsm-photos"
    minio_secure: bool = False

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
        "technician_app_url",
        "assist_model",
        "assist_embeddings",
        "anthropic_api_key",
        "openai_api_key",
        mode="before",
    )
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if isinstance(value, str) and value.strip() == "":
            return None
        return value

    @field_validator("timezone")
    @classmethod
    def _valid_iana_zone(cls, value: str) -> str:
        try:
            zoneinfo.ZoneInfo(value)
        except zoneinfo.ZoneInfoNotFoundError as exc:
            raise ValueError(f"Unknown timezone: {value!r}") from exc
        return value

    @property
    def smtp_sender_address(self) -> str | None:
        """From address for outbound mail: the SMTP account, unless smtp_from overrides it.

        The relay account we authenticate as is also the sender, so From defaults to smtp_username;
        smtp_from is set only when the sender must differ from the login. None when no account is
        configured, in which case outbound SMTP is disabled.
        """
        return self.smtp_from or self.smtp_username

    @property
    def admin_email_set(self) -> frozenset[str]:
        """Lower-cased administrator allowlist parsed from the comma-separated admin_emails."""
        if not self.admin_emails:
            return frozenset()
        return frozenset(
            part.strip().lower() for part in self.admin_emails.split(",") if part.strip()
        )

    def _provider_key_present(self, model: str | None) -> bool:
        """A provider:model string is usable only when its provider's API key is configured.

        An unknown provider yields False; building the client fails fast with the
        unknown-provider error if it is ever attempted.
        """
        if model is None:
            return False
        provider = model.split(":", 1)[0]
        key = {"openai": self.openai_api_key, "anthropic": self.anthropic_api_key}.get(provider)
        return key is not None

    @property
    def assist_kb_enabled(self) -> bool:
        """The knowledge base needs an embeddings model and the API key of its provider."""
        return self._provider_key_present(self.assist_embeddings)

    @property
    def assist_chat_enabled(self) -> bool:
        """The triage chat needs a chat model and the API key of its provider."""
        return self._provider_key_present(self.assist_model)


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
