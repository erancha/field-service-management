"""Chat-model construction is gated on configuration and never touches a provider when unset."""
from __future__ import annotations

from fsm.platform.assist_factory import build_chat_model
from fsm.platform.config import Settings

DB_URL = "postgresql+psycopg://u:p@localhost/db"


def test_returns_none_when_no_chat_model_is_configured() -> None:
    assert build_chat_model(Settings(database_url=DB_URL)) is None


def test_returns_none_when_the_provider_key_is_missing() -> None:
    settings = Settings(assist_model="anthropic:claude-sonnet-5", database_url=DB_URL)

    assert build_chat_model(settings) is None


def test_builds_a_chat_model_for_a_configured_provider(monkeypatch) -> None:
    captured: dict = {}

    def fake_init_chat_model(model: str, **kwargs):
        captured["model"] = model
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr("fsm.platform.assist_factory.init_chat_model", fake_init_chat_model)
    settings = Settings(
        assist_model="anthropic:claude-sonnet-5",
        anthropic_api_key="sk-test",
        database_url=DB_URL,
    )

    built = build_chat_model(settings)

    assert built is not None
    assert captured["model"] == "anthropic:claude-sonnet-5"
    assert captured["kwargs"] == {"api_key": "sk-test"}


def test_passes_the_openai_key_when_the_model_is_openai(monkeypatch) -> None:
    captured: dict = {}
    monkeypatch.setattr(
        "fsm.platform.assist_factory.init_chat_model",
        lambda model, **kwargs: captured.update(model=model, kwargs=kwargs) or object(),
    )
    settings = Settings(
        assist_model="openai:gpt-4.1", openai_api_key="sk-openai", database_url=DB_URL
    )

    assert build_chat_model(settings) is not None
    assert captured["kwargs"] == {"api_key": "sk-openai"}
