"""The system prompt carries the safety boundary, the control markers, and retrieved excerpts."""
from __future__ import annotations

import uuid

from fsm.assist.application.prompts import (
    CLOSED_MARKER,
    EQUIPMENT_CLOSE,
    EQUIPMENT_OPEN,
    ESCALATE_MARKER,
    MARKERS,
    QUESTION_CLOSE,
    QUESTION_OPEN,
    RESUME_MARKER,
    SKIP_MARKER,
    SOLVED_MARKER,
    SUMMARY_SYSTEM_PROMPT,
    TRIAGE_SYSTEM_PROMPT,
    ParsedReply,
    QuestionSpan,
    build_summary_prompt,
    build_system_prompt,
    parse_reply,
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
    """A marker the parser honours but the prompt never explains is one the model cannot write."""
    for marker in MARKERS:
        assert marker in TRIAGE_SYSTEM_PROMPT


def test_prompt_asks_the_model_to_name_the_equipment_and_rename_it_when_it_changes() -> None:
    section = TRIAGE_SYSTEM_PROMPT.split("Naming the equipment:", 1)[1].split("\n\n", 1)[0].lower()

    assert "the moment you can tell what the equipment is" in section
    assert "the last name you wrap is the one that stands" in section
    assert "the customer reads it" in section


def test_prompt_requires_the_customers_agreement_before_escalating() -> None:
    prompt = TRIAGE_SYSTEM_PROMPT.lower()

    assert "whether to book" in prompt
    assert "after the customer agrees" in prompt


def test_equipment_wrapper_spells_equipment_out() -> None:
    """"EQ" also reads as an abbreviation of other things; the wrapper names what it wraps."""
    assert EQUIPMENT_OPEN == "[[EQUIP]]"
    assert EQUIPMENT_CLOSE == "[[/EQUIP]]"


def test_prompt_treats_a_skip_request_as_the_yes_to_a_visit() -> None:
    prompt = TRIAGE_SYSTEM_PROMPT

    assert SKIP_MARKER in prompt
    assert RESUME_MARKER in prompt
    assert "their yes to a technician visit" in prompt.lower()


def test_prompt_states_the_minimum_a_service_call_needs_even_when_triage_is_skipped() -> None:
    """Skipping means skipping the fixes, not the description: the call cannot be opened until the
    customer has said what the equipment is and what it is doing wrong, in words or in a photo."""
    section = TRIAGE_SYSTEM_PROMPT.split("Skipping the troubleshooting:", 1)[1].split("\n\n", 1)[0]

    assert "what the equipment is and what it is doing wrong" in section
    assert "shown in a photo" in section
    assert "at least that much" in section
    assert "one focused question at a time" in section


def test_declined_prompt_forbids_fixes_and_aims_the_conversation_at_escalation() -> None:
    declined = build_system_prompt([], triage_declined=True)

    assert TRIAGE_SYSTEM_PROMPT in declined
    directive = declined.split(TRIAGE_SYSTEM_PROMPT, 1)[1]
    assert "already agreed to a service call" in directive
    assert "do not suggest fixes" in directive.lower()
    assert ESCALATE_MARKER in directive
    assert RESUME_MARKER in directive


def test_declined_directive_holds_the_same_minimum_before_the_call_can_open() -> None:
    directive = build_system_prompt([], triage_declined=True).split(TRIAGE_SYSTEM_PROMPT, 1)[1]

    assert "what the equipment is and what it is doing wrong" in directive
    assert "shown in a photo" in directive
    assert "at least that much" in directive
    assert "one focused question at a time" in directive


def test_declined_directive_rides_along_with_retrieved_excerpts() -> None:
    declined = build_system_prompt(
        [hit("oven-guide.md", "Hold the reset button.")], triage_declined=True
    )

    assert "Hold the reset button." in declined
    assert "already agreed to a service call" in declined


def test_prompt_keeps_a_declined_safety_escalation_away_from_self_help() -> None:
    prompt = TRIAGE_SYSTEM_PROMPT.lower()

    assert "declining does not reopen self-help" in prompt


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


def test_triage_prompt_fixes_how_a_step_s_result_is_asked_for() -> None:
    """A step left with nothing to answer, or asked after vaguely, costs the customer a turn.

    Vague wording that drifts between turns leaves them answering about the wrong attempt; a
    message trailing off after the instruction leaves them typing what a tap would have said.
    """
    prompt = TRIAGE_SYSTEM_PROMPT.lower()

    assert "as a yes or no naming the step" in prompt
    assert "never leave the instruction standing on its own" in prompt
    assert "which attempt you mean" in prompt


def test_triage_prompt_keeps_working_the_problem_after_a_step_changes_nothing() -> None:
    prompt = TRIAGE_SYSTEM_PROMPT.lower()

    assert "narrowed the fault" in prompt
    assert "not at the first setback" in prompt


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


def test_summary_prompt_states_the_equipment_triage_identified() -> None:
    prompt = build_summary_prompt("Bruno VPL-3100 vertical platform lift")

    assert SUMMARY_SYSTEM_PROMPT in prompt
    assert "already been identified as: Bruno VPL-3100 vertical platform lift" in prompt


def test_summary_prompt_leaves_an_unidentified_machine_to_the_transcript() -> None:
    assert build_summary_prompt(None) == SUMMARY_SYSTEM_PROMPT


def test_prompt_prefers_a_closed_question_but_not_where_the_answer_is_a_value() -> None:
    """Naming the suspicion beats sending the customer off to observe: it answers with one tap."""
    prompt = TRIAGE_SYSTEM_PROMPT.lower()

    assert "whenever a yes or no tells you what you need" in prompt
    assert "leave a question open only when no yes or no could carry the answer" in prompt
    assert "an error code" in prompt


def test_prompt_tells_the_model_to_wrap_the_question_and_nothing_else() -> None:
    prompt = TRIAGE_SYSTEM_PROMPT.lower()

    assert "wrap that question" in prompt
    assert "and nothing else, not around the whole message" in prompt


def test_parse_reply_returns_plain_text_when_no_marker_is_present() -> None:
    parsed = parse_reply("Try switching it off and on.")

    assert parsed == ParsedReply(text="Try switching it off and on.", marker=None, question=None)


def test_parse_reply_extracts_and_removes_the_solved_marker() -> None:
    parsed = parse_reply(f"Glad that worked.\n{SOLVED_MARKER}")

    assert parsed.text == "Glad that worked."
    assert parsed.marker == SOLVED_MARKER


def test_parse_reply_extracts_and_removes_the_escalate_marker() -> None:
    parsed = parse_reply(f"A technician should look at this.\n{ESCALATE_MARKER}\n")

    assert parsed.text == "A technician should look at this."
    assert parsed.marker == ESCALATE_MARKER


def test_parse_reply_extracts_and_removes_the_closed_marker() -> None:
    parsed = parse_reply(f"No problem — closing this off.\n{CLOSED_MARKER}")

    assert parsed.text == "No problem — closing this off."
    assert parsed.marker == CLOSED_MARKER


def test_parse_reply_finds_a_marker_written_inline() -> None:
    parsed = parse_reply(f"Booking a visit. {ESCALATE_MARKER}")

    assert parsed.text == "Booking a visit."
    assert parsed.marker == ESCALATE_MARKER


def test_parse_reply_unwraps_a_question_and_reports_where_it_landed() -> None:
    parsed = parse_reply(f"That rules out the supply. {QUESTION_OPEN}Is the stop out?{QUESTION_CLOSE}")

    assert parsed.text == "That rules out the supply. Is the stop out?"
    assert parsed.marker is None
    assert parsed.question == QuestionSpan(27, 43)
    assert parsed.text[parsed.question.start:parsed.question.end] == "Is the stop out?"


def test_parse_reply_spans_a_question_that_is_the_whole_reply() -> None:
    parsed = parse_reply(f"{QUESTION_OPEN}Is the display lit?{QUESTION_CLOSE}")

    assert parsed.text == "Is the display lit?"
    assert parsed.question == QuestionSpan(0, 19)


def test_parse_reply_offsets_survive_leading_whitespace_the_model_wrote() -> None:
    parsed = parse_reply(f"\n\nGood. {QUESTION_OPEN}Is it lit?{QUESTION_CLOSE}\n")

    assert parsed.text == "Good. Is it lit?"
    assert parsed.text[parsed.question.start:parsed.question.end] == "Is it lit?"


def test_parse_reply_excludes_whitespace_the_model_left_inside_the_wrapper() -> None:
    parsed = parse_reply(f"Good. {QUESTION_OPEN} Is it lit? {QUESTION_CLOSE}")

    assert parsed.text == "Good.  Is it lit?"
    assert parsed.text[parsed.question.start:parsed.question.end] == "Is it lit?"


def test_parse_reply_drops_an_unclosed_wrapper_without_reporting_a_question() -> None:
    parsed = parse_reply(f"Good. {QUESTION_OPEN}Is it lit?")

    assert parsed.text == "Good. Is it lit?"
    assert parsed.question is None


def test_parse_reply_carries_both_an_ending_and_no_question() -> None:
    parsed = parse_reply(f"Opening the service call now.\n{ESCALATE_MARKER}")

    assert parsed.marker == ESCALATE_MARKER
    assert parsed.question is None


def test_parse_reply_reports_the_equipment_and_leaves_its_name_in_the_reply() -> None:
    parsed = parse_reply(
        f"That looks like a {EQUIPMENT_OPEN}Bruno VPL-3100 vertical platform lift{EQUIPMENT_CLOSE}."
    )

    assert parsed.equipment == "Bruno VPL-3100 vertical platform lift"
    assert parsed.text == "That looks like a Bruno VPL-3100 vertical platform lift."


def test_parse_reply_keeps_a_sentence_that_reads_through_the_equipment_name_intact() -> None:
    """The name is prose the customer reads, so unwrapping it mid-sentence must not gap the text."""
    parsed = parse_reply(
        f"The {EQUIPMENT_OPEN}Bruno VPL-3100{EQUIPMENT_CLOSE} will not travel unlatched."
    )

    assert parsed.text == "The Bruno VPL-3100 will not travel unlatched."


def test_parse_reply_reports_no_equipment_when_the_reply_names_none() -> None:
    assert parse_reply("Tell me more about the problem.").equipment is None


def test_parse_reply_measures_the_question_after_the_equipment_delimiters_have_gone() -> None:
    """Both spans index the text the customer sees, so an earlier wrapper must not shift them."""
    parsed = parse_reply(
        f"A {EQUIPMENT_OPEN}Savaria Eclipse home elevator{EQUIPMENT_CLOSE}, then. "
        f"{QUESTION_OPEN}Is it lit?{QUESTION_CLOSE}"
    )

    assert parsed.text[parsed.question.start:parsed.question.end] == "Is it lit?"


def test_parse_reply_drops_a_half_written_name_without_reporting_one() -> None:
    parsed = parse_reply(f"That is a {EQUIPMENT_OPEN}Bruno VPL")

    assert parsed.equipment is None
    assert parsed.text == "That is a Bruno VPL"


def test_parse_reply_reports_a_skip_request_and_removes_its_marker() -> None:
    parsed = parse_reply(f"Understood — what is the equipment?\n{SKIP_MARKER}")

    assert parsed.triage_declined is True
    assert parsed.marker is None
    assert parsed.text == "Understood — what is the equipment?"


def test_parse_reply_reports_a_resumed_triage_and_removes_its_marker() -> None:
    parsed = parse_reply(f"Happy to try a fix. {RESUME_MARKER}Is the display lit?")

    assert parsed.triage_declined is False
    assert parsed.text == "Happy to try a fix. Is the display lit?"


def test_parse_reply_reports_no_mode_change_when_the_reply_carries_neither_marker() -> None:
    assert parse_reply("Is the display lit?").triage_declined is None


def test_parse_reply_carries_a_skip_and_an_escalation_in_one_reply() -> None:
    parsed = parse_reply(f"Opening the call now.\n{SKIP_MARKER}\n{ESCALATE_MARKER}")

    assert parsed.triage_declined is True
    assert parsed.marker == ESCALATE_MARKER
    assert parsed.text == "Opening the call now."


def test_parse_reply_measures_the_question_after_a_mode_marker_has_gone() -> None:
    parsed = parse_reply(
        f"{SKIP_MARKER}Fine. {QUESTION_OPEN}Is it the lift outside?{QUESTION_CLOSE}"
    )

    assert parsed.triage_declined is True
    assert parsed.text[parsed.question.start:parsed.question.end] == "Is it the lift outside?"


def test_parse_reply_treats_an_empty_pair_as_naming_nothing() -> None:
    parsed = parse_reply(f"Right. {EQUIPMENT_OPEN}{EQUIPMENT_CLOSE}Is it lit?")

    assert parsed.equipment is None
    assert parsed.text == "Right. Is it lit?"
