"""Renders parts of a calendar event description as the basic HTML Google Calendar accepts.

Google renders a description as HTML, so the structure a technician scans on a phone is expressed in
markup: every heading is bold and everything under one is a bullet, giving a flat run of headings
rather than a nested tree. The appointment card renders the same shape from the same structure.
Nothing here parses text — every renderer is handed what it prints, and customer-written values are
escaped.
"""
from __future__ import annotations

from collections.abc import Sequence
from html import escape

from fsm.assist.ports.chat_model import SummaryBlock

BLOCK_SEPARATOR = "<br><br>"


def blocks_html(blocks: Sequence[SummaryBlock]) -> str:
    """Render the triage summary's layout: each block a bold heading over its bullets."""
    return BLOCK_SEPARATOR.join(
        _block_html(block) for block in blocks if block.bullets or block.fields
    )


def fields_html(fields: Sequence[tuple[str, str]]) -> str:
    """Render standalone labelled lines — the contact details that are not part of the summary."""
    return "<br>".join(_field_html(label, value) for label, value in fields)


def text_html(text: str) -> str:
    """Render free text written by hand, keeping the author's line breaks."""
    return "<br>".join(_escaped(line) for line in text.split("\n"))


def _block_html(block: SummaryBlock) -> str:
    items = [_escaped(bullet) for bullet in block.bullets]
    items += [_field_html(label, value) for label, value in block.fields]
    return f"<b>{_escaped(block.heading)}:</b><ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>"


def _field_html(label: str, value: str) -> str:
    return f"<b>{_escaped(label)}:</b> {_escaped(value)}"


def _escaped(value: str) -> str:
    """Escape customer-written text into an HTML text node.

    Quotes are left as typed: nothing here is interpolated into an attribute, and a technician
    reading a quoted symptom should see the quote mark rather than an entity.
    """
    return escape(value, quote=False)
