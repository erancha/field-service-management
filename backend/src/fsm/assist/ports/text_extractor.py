"""Outbound port for turning an uploaded file into plain text."""
from typing import Protocol, runtime_checkable


@runtime_checkable
class TextExtractor(Protocol):
    def extract(self, filename: str, media_type: str, content: bytes) -> str:
        """Plain text of the document; raises UnsupportedDocumentType for unknown formats.

        The text is free of NUL, which the index stores in a Postgres text column that rejects it.
        """
        ...
