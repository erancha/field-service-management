"""The calendar event description is basic HTML, so a technician can scan it on a phone."""
from __future__ import annotations

from fsm.platform.calendar_bridge.description_html import render_description


def test_blocks_are_separated_by_a_blank_line() -> None:
    rendered = render_description(["Problem: No hot water", "Phone: +972-50-123"])

    assert rendered == "<b>Problem:</b> No hot water<br><br><b>Phone:</b> +972-50-123"


def test_action_items_become_a_bullet_list() -> None:
    rendered = render_description(
        [
            "Problem: Fault code F5\n"
            "\n"
            "Action items:\n"
            "- Bring the inDOMO HP fault list\n"
            "- Confirm where F5 is displayed\n"
            "Equipment: Arealift inDOMO HP home lift"
        ]
    )

    assert rendered == (
        "<b>Problem:</b> Fault code F5<br><br><b>Action items:</b>"
        "<ul><li>Bring the inDOMO HP fault list</li>"
        "<li>Confirm where F5 is displayed</li></ul>"
        "<b>Equipment:</b> Arealift inDOMO HP home lift"
    )


def test_markup_in_the_customer_s_words_is_escaped() -> None:
    rendered = render_description(["Symptoms: shows <F5> & then stops"])

    assert rendered == "<b>Symptoms:</b> shows &lt;F5&gt; &amp; then stops"


def test_a_line_that_is_not_a_labelled_field_is_left_alone() -> None:
    """Only a short leading label is bolded, so prose with a colon in it stays prose."""
    rendered = render_description(["Customer said the fault appeared at 10:30 yesterday"])

    assert rendered == "Customer said the fault appeared at 10:30 yesterday"
