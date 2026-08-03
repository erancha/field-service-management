"""Configuration every backend process needs, loaded from the environment."""

from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class CoreSettings(BaseSettings):
    """Base an application's own settings class extends with its product-specific fields.

    Immutable once constructed. Values come from the environment, falling back to a .env file
    beside the working directory; unknown keys are ignored so one file can serve several
    processes.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    database_url: SecretStr
    app_env: Literal["local", "test", "staging", "prod"] = "local"
    # Broker URL backing the cross-process event bus. Unset selects the in-process bus, which
    # reaches only streams held open by this process.
    redis_url: str | None = None
