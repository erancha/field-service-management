"""Renders a calendar event description as the basic HTML Google Calendar accepts.

The description arrives as plain-text blocks assembled from the service call's triage summary and
the appointment's own fields. This module gives that text the structure a technician can scan on a
phone before a visit: a "Label: value" line keeps its label in bold, a run of "- " lines becomes a
bullet list, and every other line is escaped and carried through as written.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from html import escape

# A field label is short and alphabetic. The bound is what keeps prose that merely contains a
# colon ("the fault appeared at 10:30 yesterday") from being read as a labelled field.
_LABELLED_LINE = re.compile(r"^(?P<label>[A-Za-z][A-Za-z ]{0,29}):(?P<value>.*)$")

_BULLET = "- "


def render_description(blocks: Sequence[str]) -> str:
    """Render the description blocks as one HTML document, a blank line between blocks."""
    return "<br><br>".join(_block_html(block) for block in blocks)


def _block_html(block: str) -> str:
    """Render one block, collecting each run of bullet lines into a single list."""
    rendered: list[str] = []
    bullets: list[str] = []
    for line in block.split("\n"):
        if line.startswith(_BULLET):
            bullets.append(f"<li>{_text(line[len(_BULLET):])}</li>")
            continue
        if bullets:
            rendered.append(_list_html(bullets))
            bullets = []
        rendered.append(_line_html(line))
    if bullets:
        rendered.append(_list_html(bullets))
    return _joined(rendered)


def _list_html(items: list[str]) -> str:
    return f"<ul>{''.join(items)}</ul>"


def _joined(parts: list[str]) -> str:
    """Join rendered parts; a list brings its own line breaks, two text lines need one between."""
    html = ""
    for part in parts:
        if html and not html.endswith("</ul>") and not part.startswith("<ul>"):
            html += "<br>"
        html += part
    return html


def _line_html(line: str) -> str:
    """Bold the leading label of a "Label: value" line; render anything else as plain text."""
    match = _LABELLED_LINE.match(line)
    if match is None:
        return _text(line)
    return f"<b>{match['label']}:</b>{_text(match['value'])}"


def _text(value: str) -> str:
    """Escape customer-written text into an HTML text node.

    Quotes are left as typed: nothing here is interpolated into an attribute, and a technician
    reading a quoted symptom should see the quote mark rather than an entity.
    """
    return escape(value, quote=False)
