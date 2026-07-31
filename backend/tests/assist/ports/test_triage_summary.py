"""The escalation summary is what a technician reads on the service call."""
from __future__ import annotations

from fsm.assist.ports.chat_model import TriageSummary

SUMMARY = TriageSummary(
    equipment="Bosch HBA5570 built-in oven",
    problem_category="Not heating",
    symptoms="Fan runs and the light works, but the cavity stays cold on any setting.",
    steps_tried="Reset at the breaker — no change. Checked the timer is not on delay — it was not.",
    suspected_cause="Failed heating element or thermostat.",
    action_items=(
        "Bring a spare HBA5570 heating element",
        "Check thermostat continuity before replacing anything",
    ),
)


def test_render_leads_with_the_fault_category() -> None:
    """The first line becomes the calendar event title, so it carries the fault, not a label."""
    assert SUMMARY.render().splitlines()[0] == "Not heating"


def test_render_sets_the_fault_category_off_from_what_follows() -> None:
    """A blank line, so a surface that renders the text as-is does not run the two together."""
    assert SUMMARY.render().splitlines()[1] == ""


def test_render_lists_the_action_items_above_the_background() -> None:
    rendered = SUMMARY.render()

    assert "Action items:" in rendered
    for item in SUMMARY.action_items:
        assert f"- {item}" in rendered
    assert rendered.index("Action items:") < rendered.index("Equipment:")


def test_render_labels_every_background_field() -> None:
    rendered = SUMMARY.render()

    assert "Equipment: Bosch HBA5570 built-in oven" in rendered
    assert "Symptoms:" in rendered
    assert "Steps tried:" in rendered
    assert "Suspected cause: Failed heating element or thermostat." in rendered


def test_render_keeps_field_values_intact() -> None:
    assert SUMMARY.symptoms in SUMMARY.render()
    assert SUMMARY.steps_tried in SUMMARY.render()
