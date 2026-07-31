"""The escalation summary's layout, which every surface renders and none of them re-derives."""
from __future__ import annotations

import pytest

from fsm.assist.ports.chat_model import SummaryBlock, TriageSummary

SUMMARY = TriageSummary(
    equipment="Bosch HBA5570 built-in oven",
    problem_category="Not heating",
    symptoms="Fan runs and the light works, but the cavity stays cold on any setting.",
    suspected_cause="Failed heating element or thermostat.",
    action_items=(
        "Bring a spare HBA5570 heating element",
        "Check thermostat continuity before replacing anything",
    ),
    steps_ruled_out=(
        "Breaker reset — no change, so it is not a tripped supply",
        "Timer checked, not on delay",
    ),
)


def _block(summary: TriageSummary, heading: str) -> SummaryBlock:
    return next(block for block in summary.blocks() if block.heading == heading)


class TestLayout:
    def test_the_headings_are_one_flat_run_with_nothing_grouping_them(self) -> None:
        """What the technician needs before setting out leads; the background follows."""
        assert [block.heading for block in SUMMARY.blocks()] == [
            "Problem",
            "Action items",
            "Triage summary",
            "Steps ruled out",
        ]

    def test_the_fault_leads_the_problem_and_the_symptoms_follow(self) -> None:
        assert _block(SUMMARY, "Problem").bullets == (SUMMARY.problem_category, SUMMARY.symptoms)

    def test_the_symptoms_are_not_repeated_in_the_background(self) -> None:
        """The symptoms lead as a Problem bullet; nothing restates them further down."""
        fields = _block(SUMMARY, "Triage summary").fields

        assert [label for label, _ in fields] == ["Equipment", "Suspected cause"]

    def test_the_action_items_and_ruled_out_steps_are_bullets(self) -> None:
        assert _block(SUMMARY, "Action items").bullets == SUMMARY.action_items
        assert _block(SUMMARY, "Steps ruled out").bullets == SUMMARY.steps_ruled_out

    def test_headline_is_the_fault_alone(self) -> None:
        """A surface with one line to spend — the event title, the dashboard row — shows this."""
        assert SUMMARY.headline() == "Not heating"

    def test_a_block_never_carries_bullets_and_fields_at_once(self) -> None:
        with pytest.raises(ValueError):
            SummaryBlock("Problem", bullets=("a",), fields=(("Equipment", "oven"),))

    def test_a_block_the_conversation_gave_nothing_for_is_allowed(self) -> None:
        assert SummaryBlock("Steps ruled out").bullets == ()


class TestTextProjection:
    def test_render_walks_the_same_layout(self) -> None:
        assert SUMMARY.render() == "\n".join(
            [
                "Problem:",
                "- Not heating",
                "- Fan runs and the light works, but the cavity stays cold on any setting.",
                "",
                "Action items:",
                "- Bring a spare HBA5570 heating element",
                "- Check thermostat continuity before replacing anything",
                "",
                "Triage summary:",
                "- Equipment: Bosch HBA5570 built-in oven",
                "- Suspected cause: Failed heating element or thermostat.",
                "",
                "Steps ruled out:",
                "- Breaker reset — no change, so it is not a tripped supply",
                "- Timer checked, not on delay",
            ]
        )

    def test_a_block_the_conversation_gave_nothing_for_prints_no_heading(self) -> None:
        rendered = TriageSummary(
            equipment="Oven",
            problem_category="Not heating",
            symptoms="Stays cold",
            suspected_cause="Undetermined",
            action_items=("Inspect the element",),
            steps_ruled_out=(),
        ).render()

        assert "Steps ruled out" not in rendered


class TestStorage:
    def test_a_summary_survives_the_round_trip_through_stored_json(self) -> None:
        assert TriageSummary.from_dict(SUMMARY.as_dict()) == SUMMARY

    def test_as_dict_is_json_native_so_the_column_can_hold_it(self) -> None:
        stored = SUMMARY.as_dict()

        assert stored["action_items"] == list(SUMMARY.action_items)
        assert stored["steps_ruled_out"] == list(SUMMARY.steps_ruled_out)

    def test_a_row_missing_a_field_raises_rather_than_rendering_half_a_summary(self) -> None:
        incomplete = SUMMARY.as_dict()
        del incomplete["suspected_cause"]

        with pytest.raises(KeyError):
            TriageSummary.from_dict(incomplete)
