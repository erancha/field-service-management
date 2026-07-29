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

    def render(self) -> str:
        """The service-call description text; the single place this summary is formatted."""
        return "\n".join(
            [
                f"Equipment: {self.equipment}",
                f"Problem category: {self.problem_category}",
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
