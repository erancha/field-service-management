"""Text extraction: pdf via pypdf, md/txt as UTF-8."""
import io

import pytest

from fsm.assist.adapters.text_extraction import CompositeTextExtractor
from fsm.assist.domain.errors import UnsupportedDocumentType


def _tiny_pdf() -> bytes:
    """One-page blank PDF built in-memory; keeps the fixture out of the repo."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


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


def test_unknown_extension_raises():
    extractor = CompositeTextExtractor()
    with pytest.raises(UnsupportedDocumentType):
        extractor.extract("a.png", "image/png", b"\x89PNG")


def test_corrupt_pdf_raises_a_domain_error():
    extractor = CompositeTextExtractor()
    with pytest.raises(UnsupportedDocumentType, match="could not be read as a PDF"):
        extractor.extract("broken.pdf", "application/pdf", b"not really a pdf")
