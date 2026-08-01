"""Unit tests of the Content-Disposition builder shared by the routes that serve stored files.

The HTTP paths that use it are covered where those routes are tested.
"""
from __future__ import annotations

from fsm.platform.api.downloads import content_disposition


def test_a_slash_in_the_filename_is_percent_encoded_in_the_extended_form():
    """RFC 5987's attr-char grammar has no place for a bare "/", so the extended
    filename* value must carry it percent-encoded."""
    header = content_disposition("attachment", "boiler/plate.jpg", fallback="photo")

    assert "filename*=UTF-8''boiler%2Fplate.jpg" in header


def test_a_backslash_never_reaches_the_header():
    """Inside the quoted fallback a trailing backslash escapes the closing quote, leaving
    the header unterminated for a strict RFC 7230 parser, so backslashes are stripped."""
    header = content_disposition("attachment", "plate.jpg\\", fallback="photo")

    assert "\\" not in header
    assert "%5C" not in header
    assert 'filename="plate.jpg"' in header


def test_a_filename_with_no_ascii_falls_back_to_the_caller_s_name():
    header = content_disposition("inline", "מדריך", fallback="document")

    assert 'filename="document"' in header
    assert "filename*=UTF-8''" in header
