"""Builds the assist context's adapters from configuration (composition root helpers)."""
from __future__ import annotations

from langchain.embeddings import init_embeddings
from langchain_core.embeddings import Embeddings

from fsm.assist.adapters.text_extraction import CompositeTextExtractor
from fsm.assist.adapters.vector_index import PgVectorDocumentIndex
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


def build_text_extractor() -> TextExtractor:
    return CompositeTextExtractor()
