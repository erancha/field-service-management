"""Outbound port for the conversational model behind the triage assistant."""
from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from fsm.assist.domain.conversation import Message


@dataclass(frozen=True)
class SummaryBlock:
    """A heading over one kind of content: a bullet list, or labelled fields — never both.

    Which one a block carries is fixed by the layout, so a renderer can branch on it without
    inspecting the values. Both empty is a block the conversation gave nothing for — nothing was
    ruled out, say — and every renderer omits it, heading included.
    """

    heading: str
    bullets: tuple[str, ...] = ()
    fields: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if self.bullets and self.fields:
            raise ValueError(f"block {self.heading!r} carries both bullets and fields")


@dataclass(frozen=True)
class TriageSummary:
    """What the assistant learned, written for the technician who takes the job."""

    equipment: str
    problem_category: str
    symptoms: str
    suspected_cause: str
    action_items: tuple[str, ...]
    steps_ruled_out: tuple[str, ...]

    def blocks(self) -> tuple[SummaryBlock, ...]:
        """The layout of the summary, and the only definition of it.

        Every surface — the calendar event, the appointment card, the notification email — walks
        this sequence, so they present the same headings in the same order and none of them
        re-derives the shape from rendered text.

        One flat run of headings, no grouping above them: what a technician needs before setting
        out comes first, and what is worth reading on the way follows. The fault leads the Problem
        block because a surface with one line to spend shows that line, and it is the headline.
        """
        return (
            SummaryBlock("Problem", bullets=(self.problem_category, self.symptoms)),
            SummaryBlock("Action items", bullets=self.action_items),
            SummaryBlock(
                "Triage summary",
                fields=(
                    ("Equipment", self.equipment),
                    ("Suspected cause", self.suspected_cause),
                ),
            ),
            SummaryBlock("Steps ruled out", bullets=self.steps_ruled_out),
        )

    def headline(self) -> str:
        """The fault in one line, for a surface that has only one to spend."""
        return self.problem_category

    def render(self) -> str:
        """The plain-text projection of the layout, stored as the service call's description.

        Anything that reads a service call as text — the notification email, a feed row — gets the
        same headings in the same order as the surfaces that render the structure directly.
        """
        lines: list[str] = []
        for block in self.blocks():
            if not block.bullets and not block.fields:
                continue
            if lines:
                lines.append("")
            lines.append(f"{block.heading}:")
            lines.extend(f"- {bullet}" for bullet in block.bullets)
            lines.extend(f"- {label}: {value}" for label, value in block.fields)
        return "\n".join(lines)

    def as_dict(self) -> dict[str, Any]:
        """The summary as the JSON stored on the service call; blocks() lays it back out."""
        return {
            "equipment": self.equipment,
            "problem_category": self.problem_category,
            "symptoms": self.symptoms,
            "suspected_cause": self.suspected_cause,
            "action_items": list(self.action_items),
            "steps_ruled_out": list(self.steps_ruled_out),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TriageSummary:
        """Rebuild a summary from stored JSON; a row missing a field is a broken write, not a case."""
        return cls(
            equipment=data["equipment"],
            problem_category=data["problem_category"],
            symptoms=data["symptoms"],
            suspected_cause=data["suspected_cause"],
            action_items=tuple(data["action_items"]),
            steps_ruled_out=tuple(data["steps_ruled_out"]),
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
