"""Text extraction: pdf via pypdf, md/txt as UTF-8."""
import io

import pytest

from fsm.assist.adapters.text_extraction import CompositeTextExtractor
from fsm.assist.domain.errors import UnsupportedDocumentType


def _pdf_with_pages(count: int) -> bytes:
    """Blank multi-page PDF built in-memory; keeps fixtures out of the repo."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(count):
        writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _tiny_pdf() -> bytes:
    return _pdf_with_pages(1)


def test_extracts_plain_text():
    extractor = CompositeTextExtractor()
    assert extractor.extract("a.txt", "text/plain", b"hello") == "hello"


def test_extracts_markdown_as_text():
    extractor = CompositeTextExtractor()
    assert extractor.extract("a.md", "text/markdown", b"# Title\nBody") == "# Title\nBody"


def test_pdf_roundtrip_yields_empty_text_for_blank_page():
    # pypdf cannot easily author text content; a blank page proves the pdf path runs
    # end-to-end and returns a string (emptiness is then caught by the application layer).
    extractor = CompositeTextExtractor()
    result = extractor.extract("a.pdf", "application/pdf", _tiny_pdf())
    assert isinstance(result, str)


@pytest.mark.parametrize(
    ("name", "media_type"),
    [("a.txt", "text/plain"), ("a.md", "text/markdown"), ("a.pdf", "application/pdf")],
)
def test_extracted_text_carries_no_nul_byte(name, media_type):
    """A NUL survives to the chunk table otherwise, and Postgres text rejects it outright —
    failing the whole document over one unmappable glyph."""
    extractor = CompositeTextExtractor()
    content = _tiny_pdf() if name.endswith(".pdf") else b"before\x00after"
    assert "\x00" not in extractor.extract(name, media_type, content)


def test_nul_becomes_a_separator_rather_than_joining_its_neighbours():
    extractor = CompositeTextExtractor()
    assert extractor.extract("a.txt", "text/plain", b"WORD\x00NEXT") == "WORD NEXT"


def test_pdf_extraction_reports_per_page_progress():
    """The page count is reported before page one, then each page read reports
    (pages done, total pages) — a long extraction shows a bar immediately, then movement."""
    extractor = CompositeTextExtractor()
    reported: list[tuple[int, int]] = []
    extractor.extract(
        "a.pdf",
        "application/pdf",
        _pdf_with_pages(3),
        on_progress=lambda done, total: reported.append((done, total)),
    )
    assert reported == [(0, 3), (1, 3), (2, 3), (3, 3)]


def test_text_decode_reports_no_progress():
    """UTF-8 decode has no sub-steps worth reporting; only formats with real phases report."""
    extractor = CompositeTextExtractor()
    reported: list[tuple[int, int]] = []
    extractor.extract(
        "a.txt", "text/plain", b"hello", on_progress=lambda d, t: reported.append((d, t))
    )
    assert reported == []


def test_unknown_extension_raises():
    extractor = CompositeTextExtractor()
    with pytest.raises(UnsupportedDocumentType):
        extractor.extract("a.png", "image/png", b"\x89PNG")


def test_corrupt_pdf_raises_a_domain_error():
    extractor = CompositeTextExtractor()
    with pytest.raises(UnsupportedDocumentType, match="could not be read as a PDF"):
        extractor.extract("broken.pdf", "application/pdf", b"not really a pdf")
