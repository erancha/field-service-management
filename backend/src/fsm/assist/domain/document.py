"""Knowledge-base document: the source of truth the vector index is derived from."""
from __future__ import annotations

import uuid
from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ExtractedText:
    """A document's plain text with where each of its pages begins in it.

    Carrying the page starts alongside the text is what lets a chunk report its page without the
    text being split per page: chunking runs over the whole document exactly as it would without
    pages, and a chunk's offset in that text is resolved to a page afterwards.

    page_starts[i] is the offset page i+1 begins at, so it always opens with 0. It is empty for
    formats that have no pages (markdown, plain text), whose chunks report no page.
    """

    text: str
    page_starts: tuple[int, ...] = ()

    def page_of(self, offset: int) -> int | None:
        """The 1-based page this offset falls on, or None for a document without pages."""
        if not self.page_starts:
            return None
        return bisect_right(self.page_starts, offset)


@dataclass(frozen=True)
class KbDocument:
    """One uploaded knowledge-base document.

    chunk_count and embedding_model describe the index state derived from this document:
    how many chunks were written and with which embedding model, so a configuration change
    can detect an out-of-date index.
    """

    id: uuid.UUID
    filename: str
    media_type: str
    size_bytes: int
    uploaded_by: uuid.UUID
    uploaded_at: datetime
    chunk_count: int
    embedding_model: str
