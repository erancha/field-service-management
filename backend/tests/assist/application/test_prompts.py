"""The system prompt carries the safety boundary, the control markers, and retrieved excerpts."""
from __future__ import annotations

import uuid

from fsm.assist.application.prompts import (
    CLOSED_MARKER,
    ESCALATE_MARKER,
    SOLVED_MARKER,
    SUMMARY_SYSTEM_PROMPT,
    TRIAGE_SYSTEM_PROMPT,
    build_system_prompt,
    strip_markers,
)
from fsm.assist.ports.document_index import SearchHit


def hit(filename: str, content: str) -> SearchHit:
    return SearchHit(document_id=uuid.uuid4(), filename=filename, content=content, score=0.8)


def test_prompt_forbids_every_unsafe_domain() -> None:
    prompt = TRIAGE_SYSTEM_PROMPT.lower()

    for hazard in ("gas", "mains wiring", "refrigerant", "working at height"):
        assert hazard in prompt


def test_prompt_tells_the_model_to_ask_for_and_read_photos() -> None:
    prompt = TRIAGE_SYSTEM_PROMPT.lower()

    assert "rating plate" in prompt
    assert "model number" in prompt
    assert "escalate" in prompt.split("photos:", 1)[1].split("safety boundary", 1)[0]


def test_prompt_documents_every_control_marker() -> None:
    assert SOLVED_MARKER in TRIAGE_SYSTEM_PROMPT
    assert ESCALATE_MARKER in TRIAGE_SYSTEM_PROMPT
    assert CLOSED_MARKER in TRIAGE_SYSTEM_PROMPT


def test_a_search_that_found_nothing_leaves_the_prompt_untouched() -> None:
    assert build_system_prompt([]) == TRIAGE_SYSTEM_PROMPT


def test_every_hit_reaches_the_prompt_with_the_document_it_came_from() -> None:
    grounded = build_system_prompt(
        [
            hit("oven-guide.md", "Hold the reset button for ten seconds."),
            hit("boiler-manual.pdf", "Bleed the upstairs radiator first."),
        ]
    )

    assert TRIAGE_SYSTEM_PROMPT in grounded
    for source, excerpt in (
        ("oven-guide.md", "Hold the reset button for ten seconds."),
        ("boiler-manual.pdf", "Bleed the upstairs radiator first."),
    ):
        assert source in grounded
        assert excerpt in grounded


def test_grounded_prompt_asks_for_a_citation_and_allows_a_fallback() -> None:
    grounded = build_system_prompt([hit("oven-guide.md", "Hold the reset button.")]).lower()

    assert "name the document" in grounded
    assert "your own knowledge" in grounded


def test_summary_prompt_names_every_field_the_layout_renders() -> None:
    for field in (
        "problem_category",
        "symptoms",
        "action_items",
        "equipment",
        "suspected_cause",
        "steps_ruled_out",
    ):
        assert field in SUMMARY_SYSTEM_PROMPT


def test_summary_prompt_bounds_each_field_and_separates_what_is_read_when() -> None:
    prompt = SUMMARY_SYSTEM_PROMPT.lower()

    assert "one or two sentences" in prompt
    assert "before setting out" in prompt


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
