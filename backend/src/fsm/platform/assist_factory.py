"""Builds the assist context's adapters from configuration (composition root helpers)."""
from __future__ import annotations

from langchain.chat_models import init_chat_model
from langchain.embeddings import init_embeddings
from langchain_core.embeddings import Embeddings

from fsm.assist.adapters.chat_model import LangChainChatModel
from fsm.assist.adapters.text_extraction import CompositeTextExtractor
from fsm.assist.adapters.vector_index import PgVectorDocumentIndex
from fsm.assist.ports.chat_model import ChatModel
from fsm.assist.ports.document_index import DocumentIndex
from fsm.assist.ports.text_extractor import TextExtractor
from fsm.platform.config import Settings


def build_kb_index(settings: Settings) -> DocumentIndex | None:
    """The vector index, or None when the knowledge base is not configured.

    init_embeddings resolves the provider:model string and raises on an unknown provider —
    the fail-fast path for a misconfigured ASSIST_EMBEDDINGS. The provider key is passed
    explicitly rather than left to init_embeddings' env-var lookup, so the feature works
    without exporting it into the process environment.
    """
    if not settings.assist_kb_enabled:
        return None
    assert settings.assist_embeddings is not None  # guaranteed by assist_kb_enabled
    provider = settings.assist_embeddings.split(":", 1)[0]
    kwargs: dict[str, str] = {}
    if provider == "openai":
        assert settings.openai_api_key is not None  # guaranteed by assist_kb_enabled
        kwargs["api_key"] = settings.openai_api_key.get_secret_value()
    embeddings: Embeddings = init_embeddings(settings.assist_embeddings, **kwargs)
    return PgVectorDocumentIndex(
        connection_url=settings.database_url.get_secret_value(),
        embeddings=embeddings,
    )


def build_chat_model(settings: Settings) -> ChatModel | None:
    """The triage chat model, or None when the feature is not configured.

    The API key is passed explicitly rather than through the environment, so the feature works
    without exporting provider keys into the process.
    """
    if not settings.assist_chat_enabled:
        return None
    assert settings.assist_model is not None  # guaranteed by assist_chat_enabled
    provider = settings.assist_model.split(":", 1)[0]
    key = {"openai": settings.openai_api_key, "anthropic": settings.anthropic_api_key}[provider]
    assert key is not None  # guaranteed by assist_chat_enabled
    model = init_chat_model(settings.assist_model, api_key=key.get_secret_value())
    return LangChainChatModel(model)


def build_text_extractor() -> TextExtractor:
    return CompositeTextExtractor()
