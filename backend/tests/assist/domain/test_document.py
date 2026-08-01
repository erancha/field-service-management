"""The extracted text's page lookup, which is what gives a chunk its page."""
from __future__ import annotations

from fsm.assist.domain.document import ExtractedText

# Two pages of ten characters each, then a short third.
PAGED = ExtractedText(text="a" * 25, page_starts=(0, 10, 20))


def test_an_offset_on_the_first_page_reports_page_one():
    assert PAGED.page_of(0) == 1
    assert PAGED.page_of(9) == 1


def test_the_first_offset_of_a_page_belongs_to_that_page():
    assert PAGED.page_of(10) == 2
    assert PAGED.page_of(20) == 3


def test_an_offset_inside_the_last_page_reports_the_last_page():
    assert PAGED.page_of(24) == 3


def test_a_document_without_pages_reports_none():
    assert ExtractedText(text="body").page_of(0) is None
