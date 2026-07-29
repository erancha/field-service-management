"""Assist configuration: provider:model strings and the key-dependency rule for the KB."""
from fsm.platform.config import Settings

OPENAI_EMBEDDINGS = "openai:text-embedding-3-small"


def _settings(**overrides) -> Settings:
    base = {"database_url": "postgresql+psycopg://x:x@localhost/x", "app_env": "test"}
    return Settings(**{**base, **overrides})


def test_models_are_unset_unless_configured():
    s = _settings()
    assert s.assist_model is None
    assert s.assist_embeddings is None
    assert s.anthropic_api_key is None
    assert s.openai_api_key is None


def test_kb_disabled_without_an_embeddings_model():
    assert _settings(openai_api_key="sk-x").assist_kb_enabled is False


def test_kb_disabled_without_the_embedding_providers_key():
    assert _settings(assist_embeddings=OPENAI_EMBEDDINGS).assist_kb_enabled is False
    assert (
        _settings(assist_embeddings=OPENAI_EMBEDDINGS, anthropic_api_key="sk-ant").assist_kb_enabled
        is False
    )


def test_kb_enabled_when_the_embedding_providers_key_is_present():
    assert (
        _settings(assist_embeddings=OPENAI_EMBEDDINGS, openai_api_key="sk-x").assist_kb_enabled
        is True
    )


def test_blank_env_values_mean_unset():
    s = _settings(assist_model="", assist_embeddings=" ", openai_api_key="", anthropic_api_key="  ")
    assert s.assist_model is None
    assert s.assist_embeddings is None
    assert s.openai_api_key is None
    assert s.anthropic_api_key is None


def test_chat_enabled_with_anthropic_model_and_key() -> None:
    settings = Settings(
        assist_model="anthropic:claude-sonnet-5",
        anthropic_api_key="sk-test",
        database_url="postgresql+psycopg://u:p@localhost/db",
    )
    assert settings.assist_chat_enabled is True


def test_chat_disabled_without_the_matching_provider_key() -> None:
    settings = Settings(
        assist_model="anthropic:claude-sonnet-5",
        openai_api_key="sk-test",
        database_url="postgresql+psycopg://u:p@localhost/db",
    )
    assert settings.assist_chat_enabled is False


def test_chat_disabled_when_no_model_is_configured() -> None:
    settings = Settings(
        anthropic_api_key="sk-test",
        database_url="postgresql+psycopg://u:p@localhost/db",
    )
    assert settings.assist_chat_enabled is False


def test_chat_disabled_for_an_unknown_provider() -> None:
    settings = Settings(
        assist_model="mistral:large",
        anthropic_api_key="sk-test",
        database_url="postgresql+psycopg://u:p@localhost/db",
    )
    assert settings.assist_chat_enabled is False


def test_kb_and_chat_gates_are_independent() -> None:
    settings = Settings(
        assist_model="anthropic:claude-sonnet-5",
        anthropic_api_key="sk-test",
        database_url="postgresql+psycopg://u:p@localhost/db",
    )
    assert settings.assist_chat_enabled is True
    assert settings.assist_kb_enabled is False
