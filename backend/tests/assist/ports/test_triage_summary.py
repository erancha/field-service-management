"""The escalation summary is what a technician reads on the service call."""
from __future__ import annotations

from fsm.assist.ports.chat_model import TriageSummary

SUMMARY = TriageSummary(
    equipment="Bosch HBA5570 built-in oven",
    problem_category="Not heating",
    symptoms="Fan runs and the light works, but the cavity stays cold on any setting.",
    steps_tried="Reset at the breaker — no change. Checked the timer is not on delay — it was not.",
    suspected_cause="Failed heating element or thermostat.",
)


def test_render_labels_every_field() -> None:
    rendered = SUMMARY.render()

    assert "Equipment: Bosch HBA5570 built-in oven" in rendered
    assert "Problem category: Not heating" in rendered
    assert "Symptoms:" in rendered
    assert "Steps tried:" in rendered
    assert "Suspected cause: Failed heating element or thermostat." in rendered


def test_render_keeps_field_values_intact() -> None:
    assert SUMMARY.symptoms in SUMMARY.render()
    assert SUMMARY.steps_tried in SUMMARY.render()
