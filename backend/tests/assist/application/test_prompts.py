"""The system prompt carries the safety boundary and the control markers."""
from __future__ import annotations

from fsm.assist.application.prompts import (
    CLOSED_MARKER,
    ESCALATE_MARKER,
    SOLVED_MARKER,
    TRIAGE_SYSTEM_PROMPT,
    strip_markers,
)


def test_prompt_forbids_every_unsafe_domain() -> None:
    prompt = TRIAGE_SYSTEM_PROMPT.lower()

    for hazard in ("gas", "mains wiring", "refrigerant", "working at height"):
        assert hazard in prompt


def test_prompt_documents_every_control_marker() -> None:
    assert SOLVED_MARKER in TRIAGE_SYSTEM_PROMPT
    assert ESCALATE_MARKER in TRIAGE_SYSTEM_PROMPT
    assert CLOSED_MARKER in TRIAGE_SYSTEM_PROMPT


def test_strip_markers_returns_plain_text_when_no_marker_is_present() -> None:
    assert strip_markers("Try switching it off and on.") == ("Try switching it off and on.", None)


def test_strip_markers_extracts_and_removes_the_solved_marker() -> None:
    text, marker = strip_markers(f"Glad that worked.\n{SOLVED_MARKER}")

    assert text == "Glad that worked."
    assert marker == SOLVED_MARKER


def test_strip_markers_extracts_and_removes_the_escalate_marker() -> None:
    text, marker = strip_markers(f"A technician should look at this.\n{ESCALATE_MARKER}\n")

    assert text == "A technician should look at this."
    assert marker == ESCALATE_MARKER


def test_strip_markers_extracts_and_removes_the_closed_marker() -> None:
    text, marker = strip_markers(f"No problem — closing this off.\n{CLOSED_MARKER}")

    assert text == "No problem — closing this off."
    assert marker == CLOSED_MARKER


def test_strip_markers_finds_a_marker_written_inline() -> None:
    text, marker = strip_markers(f"Booking a visit. {ESCALATE_MARKER}")

    assert text == "Booking a visit."
    assert marker == ESCALATE_MARKER
