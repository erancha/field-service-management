"""Knowledge-base document: the source of truth the vector index is derived from."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


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
