"""Turns uploaded files into plain text: pypdf for PDF, UTF-8 decode for md/txt."""
from __future__ import annotations

import io
from dataclasses import replace
from pathlib import PurePosixPath

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from fsm.assist.domain.document import ExtractedText
from fsm.assist.domain.errors import UnsupportedDocumentType
from fsm.assist.ports.progress import ProgressCallback, progress_step


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
    def extract(
        self,
        filename: str,
        media_type: str,
        content: bytes,
        on_progress: ProgressCallback | None = None,
    ) -> ExtractedText:
        extracted = self._decode(filename, content, on_progress)
        # NUL is replaced by a single space rather than dropped, so normalization cannot shift the
        # page starts measured during decoding.
        return replace(extracted, text=_without_nul(extracted.text))

    def _decode(
        self, filename: str, content: bytes, on_progress: ProgressCallback | None
    ) -> ExtractedText:
        """Text as each format yields it, before the normalization extract applies to all of them.

        PDF page reads dominate ingest latency for large manuals, so that path reports progress;
        reports are stepped rather than per page to bound the event volume for long documents.
        """
        extension = PurePosixPath(filename).suffix.lower()
        if extension == ".pdf":
            try:
                reader = PdfReader(io.BytesIO(content))
                total = len(reader.pages)
                step = progress_step(total)
                if on_progress is not None:
                    on_progress(0, total)
                parts = []
                starts = []
                offset = 0
                for number, page in enumerate(reader.pages, start=1):
                    part = page.extract_text() or ""
                    starts.append(offset)
                    parts.append(part)
                    # The extra character is the newline the join puts between pages, so the
                    # next page starts after it.
                    offset += len(part) + 1
                    if on_progress is not None and (number % step == 0 or number == total):
                        on_progress(number, total)
                return ExtractedText(text="\n".join(parts), page_starts=tuple(starts))
            except PyPdfError as exc:
                raise UnsupportedDocumentType(
                    f'"{filename}" could not be read as a PDF (corrupt or unsupported format)'
                ) from exc
        if extension in {".md", ".txt"}:
            return ExtractedText(text=content.decode("utf-8"))
        raise UnsupportedDocumentType(f'"{filename}" is not a supported document type (pdf, md, txt)')
