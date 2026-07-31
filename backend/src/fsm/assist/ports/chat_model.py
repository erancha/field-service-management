"""Outbound port for the conversational model behind the triage assistant."""
from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from fsm.assist.domain.conversation import Message


@dataclass(frozen=True)
class TriageSummary:
    """What the assistant learned, written for the technician who takes the job."""

    equipment: str
    problem_category: str
    symptoms: str
    steps_tried: str
    suspected_cause: str
    action_items: tuple[str, ...]

    def render(self) -> str:
        """The service-call description text; the single place this summary is formatted.

        The fault category stands alone on the first line because the calendar event takes its
        title from it, and every surface that shows the summary labels that line itself. A blank
        line sets it off from the action items, which come above the background fields so the
        technician meets the job to be done before the evidence behind it.
        """
        return "\n".join(
            [
                self.problem_category,
                "",
                "Action items:",
                *(f"- {item}" for item in self.action_items),
                f"Equipment: {self.equipment}",
                f"Symptoms: {self.symptoms}",
                f"Steps tried: {self.steps_tried}",
                f"Suspected cause: {self.suspected_cause}",
            ]
        )


@runtime_checkable
class ChatModel(Protocol):
    """A chat model reached provider-agnostically; the adapter owns provider selection."""

    def stream(self, system: str, messages: Sequence[Message]) -> Iterator[str]:
        """Yield the reply in order as text fragments."""
        ...

    def summarize(self, system: str, messages: Sequence[Message]) -> TriageSummary:
        """Condense the exchange into the fields a technician needs."""
        ...
