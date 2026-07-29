"""Turns uploaded files into plain text: pypdf for PDF, UTF-8 decode for md/txt."""
from __future__ import annotations

import io
from pathlib import PurePosixPath

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from fsm.assist.domain.errors import UnsupportedDocumentType


def _without_nul(text: str) -> str:
    """Replace NUL with a space, the separator it almost always stands in for.

    A PDF whose embedded font carries no usable encoding decodes to the glyph codes themselves,
    and a space in such a run arrives as NUL. Postgres text columns reject NUL outright, so one
    unmappable caption would otherwise fail an entire document at whichever chunk contains it.
    Substituting rather than deleting keeps the words on either side from fusing into one token
    that matches nothing.
    """
    return text.replace("\x00", " ")


class CompositeTextExtractor:
    def extract(self, filename: str, media_type: str, content: bytes) -> str:
        return _without_nul(self._decode(filename, content))

    def _decode(self, filename: str, content: bytes) -> str:
        """Text as each format yields it, before the normalization extract applies to all of them."""
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
