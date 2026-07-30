"""LangChain-backed chat model; the provider is chosen where the model is built, not here."""
from __future__ import annotations

import base64
from collections.abc import Iterator, Sequence
from typing import cast

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from fsm.assist.domain.conversation import Message, MessageRole
from fsm.assist.ports.chat_model import TriageSummary
from fsm.assist.ports.photo_store import PhotoStore, preview_key


class _SummarySchema(BaseModel):
    """Structured-output schema; field descriptions are what the model is asked to fill in."""

    equipment: str = Field(description="Make, model, and type of the equipment.")
    problem_category: str = Field(description="Short label for the fault.")
    symptoms: str = Field(description="What the customer observes.")
    steps_tried: str = Field(description="Each step attempted and what it changed.")
    suspected_cause: str = Field(description="Best assessment, or that it is undetermined.")


_TRANSCRIPT_LABELS = {MessageRole.CUSTOMER: "Customer", MessageRole.ASSISTANT: "Assistant"}


def _to_langchain(
    system: str, messages: Sequence[Message], photo_store: PhotoStore | None
) -> list[BaseMessage]:
    turns: list[BaseMessage] = [SystemMessage(content=system)]
    for message in messages:
        if message.role is MessageRole.CUSTOMER:
            if message.photos and photo_store is not None:
                # LangChain's standard image block, accepted by both ChatAnthropic and
                # ChatOpenAI; images precede the text per provider guidance.
                blocks: list[str | dict] = [
                    {
                        "type": "image",
                        "source_type": "base64",
                        "mime_type": "image/jpeg",
                        "data": base64.b64encode(
                            photo_store.get(preview_key(photo.object_key))
                        ).decode("ascii"),
                    }
                    for photo in message.photos
                ]
                # Anthropic rejects an empty text block; a photo-only turn omits it entirely.
                if message.text:
                    blocks.append({"type": "text", "text": message.text})
                turns.append(HumanMessage(content=blocks))
            else:
                turns.append(HumanMessage(content=message.text))
        else:
            turns.append(AIMessage(content=message.text))
    return turns


def _to_transcript(messages: Sequence[Message]) -> str:
    """Render the exchange as labelled text, for a model asked to read it rather than continue it.

    A request whose last turn is the assistant's is a half-written reply the model is meant to
    carry on from, and providers reject that where they do not support it. Summarizing runs over
    a finished conversation, which always ends on the assistant's side, so the exchange goes in as
    the content of a single customer turn instead of as turns of its own.

    The transcript is text, so a turn the customer sent as photos alone stands in as [photo]:
    the summary is written for the technician, who needs to know an image was supplied even
    though this rendering cannot carry it.
    """
    return "\n\n".join(
        f"{_TRANSCRIPT_LABELS[m.role]}: {(m.text or '[photo]') if m.photos else m.text}"
        for m in messages
    )


class LangChainChatModel:
    """Adapts a configured LangChain chat model to the assist ChatModel port."""

    def __init__(self, model: BaseChatModel, photo_store: PhotoStore | None = None) -> None:
        self._model = model
        self._photo_store = photo_store

    def stream(self, system: str, messages: Sequence[Message]) -> Iterator[str]:
        for chunk in self._model.stream(_to_langchain(system, messages, self._photo_store)):
            # chunk.text keeps only the text blocks of a chunk, dropping reasoning, tool-call, and
            # metadata blocks that must never reach the customer. It recomputes on each access.
            text = chunk.text
            if text:
                yield str(text)

    def summarize(self, system: str, messages: Sequence[Message]) -> TriageSummary:
        structured = self._model.with_structured_output(_SummarySchema)
        request: list[BaseMessage] = [
            SystemMessage(content=system),
            HumanMessage(content=_to_transcript(messages)),
        ]
        result = cast(_SummarySchema, structured.invoke(request))
        return TriageSummary(
            equipment=result.equipment,
            problem_category=result.problem_category,
            symptoms=result.symptoms,
            steps_tried=result.steps_tried,
            suspected_cause=result.suspected_cause,
        )
