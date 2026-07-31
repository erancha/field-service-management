"""The calendar event description is basic HTML, rendered from the layout rather than parsed."""
from __future__ import annotations

from fsm.assist.ports.chat_model import SummaryBlock, TriageSummary
from fsm.platform.calendar_bridge.description_html import blocks_html, fields_html, text_html

SUMMARY = TriageSummary(
    equipment="Arealift inDOMO HP home lift",
    problem_category="Fault code F5",
    symptoms="Stops between floors",
    suspected_cause="Undetermined",
    action_items=("Bring the inDOMO HP fault list",),
    steps_ruled_out=("Power cycled — no change",),
)


def test_the_layout_is_one_flat_run_of_bold_headings_over_bullets() -> None:
    """No grouping above the headings: the appointment card renders this same shape."""
    rendered = blocks_html(SUMMARY.blocks())

    assert rendered == (
        "<b>Problem:</b><ul><li>Fault code F5</li><li>Stops between floors</li></ul>"
        "<br><br>"
        "<b>Action items:</b><ul><li>Bring the inDOMO HP fault list</li></ul>"
        "<br><br>"
        "<b>Triage summary:</b><ul>"
        "<li><b>Equipment:</b> Arealift inDOMO HP home lift</li>"
        "<li><b>Suspected cause:</b> Undetermined</li></ul>"
        "<br><br>"
        "<b>Steps ruled out:</b><ul><li>Power cycled — no change</li></ul>"
    )


def test_a_block_the_conversation_gave_nothing_for_prints_no_heading() -> None:
    rendered = blocks_html(
        [
            SummaryBlock("Problem", bullets=("Fault code F5",)),
            SummaryBlock("Steps ruled out", bullets=()),
        ]
    )

    assert rendered == "<b>Problem:</b><ul><li>Fault code F5</li></ul>"


def test_markup_in_the_customer_s_words_is_escaped() -> None:
    rendered = fields_html([("Symptoms", "shows <F5> & then stops")])

    assert rendered == "<b>Symptoms:</b> shows &lt;F5&gt; &amp; then stops"


def test_a_colon_in_free_text_stays_text() -> None:
    """Nothing reads the text for structure, so prose is carried through as written."""
    rendered = text_html("Customer said the fault appeared at 10:30 yesterday")

    assert rendered == "Customer said the fault appeared at 10:30 yesterday"


def test_free_text_keeps_the_author_s_line_breaks() -> None:
    assert text_html("Gate code 4321\nDog in the yard") == "Gate code 4321<br>Dog in the yard"
