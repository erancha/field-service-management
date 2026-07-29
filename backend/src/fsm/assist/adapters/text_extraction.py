"""Turns uploaded files into plain text: pypdf for PDF, UTF-8 decode for md/txt."""
from __future__ import annotations

import io
from pathlib import PurePosixPath

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from fsm.assist.domain.errors import UnsupportedDocumentType


class CompositeTextExtractor:
    def extract(self, filename: str, media_type: str, content: bytes) -> str:
        extension = PurePosixPath(filename).suffix.lower()
        if extension == ".pdf":
            try:
                reader = PdfReader(io.BytesIO(content))
                return "\n".join(page.extract_text() or "" for page in reader.pages)
            except PyPdfError as exc:
                raise UnsupportedDocumentType(
                    f'"{filename}" could not be read as a PDF (corrupt or unsupported format)'
                ) from exc
        if extension in {".md", ".txt"}:
            return content.decode("utf-8")
        raise UnsupportedDocumentType(f'"{filename}" is not a supported document type (pdf, md, txt)')
