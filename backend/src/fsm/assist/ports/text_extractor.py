"""Outbound port for turning an uploaded file into plain text."""
from typing import Protocol, runtime_checkable

from fsm.assist.ports.progress import ProgressCallback


@runtime_checkable
class TextExtractor(Protocol):
    def extract(
        self,
        filename: str,
        media_type: str,
        content: bytes,
        on_progress: ProgressCallback | None = None,
    ) -> str:
        """Plain text of the document; raises UnsupportedDocumentType for unknown formats.

        The text is free of NUL, which the index stores in a Postgres text column that rejects it.

        on_progress, when given, is called as extraction advances with (pages done, total pages).
        Only formats with real sub-steps report — PDF as pages are read; a plain-text decode is
        a single instantaneous step and reports nothing.
        """
        ...
