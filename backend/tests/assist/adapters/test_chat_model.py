"""The chat adapter maps domain turns onto LangChain messages; no provider is contacted."""
from __future__ import annotations

import base64
import uuid
from datetime import datetime, timezone

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from fsm.assist.adapters.chat_model import LangChainChatModel
from fsm.assist.domain.conversation import Message, MessageRole, Photo
from fsm.assist.ports.chat_model import ChatModel, TriageSummary
from fsm.assist.ports.photo_store import preview_key
from tests.assist.fakes import FakePhotoStore

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)


def message(role: MessageRole, text: str, photos: tuple[Photo, ...] = ()) -> Message:
    return Message(id=uuid.uuid4(), role=role, text=text, created_at=NOW, photos=photos)


class RecordingModel:
    """Stands in for a LangChain BaseChatModel; each streamed content becomes one AIMessage."""

    def __init__(self, contents=("Is ", "it ", "lit?")) -> None:
        self._contents = contents
        self.streamed: list = []
        self.structured_input: list = []

    def stream(self, messages):
        self.streamed.append(messages)
        for content in self._contents:
            yield AIMessage(content=content)

    def with_structured_output(self, schema):
        outer = self

        class _Structured:
            def invoke(self, messages):
                outer.structured_input.append(messages)
                return schema(
                    equipment="Oven",
                    problem_category="Not heating",
                    symptoms="Stays cold",
                    steps_tried="Breaker reset — no change",
                    suspected_cause="Heating element",
                )

        return _Structured()


def test_adapter_satisfies_the_port() -> None:
    assert isinstance(LangChainChatModel(RecordingModel()), ChatModel)


def test_stream_yields_text_fragments_in_order() -> None:
    adapter = LangChainChatModel(RecordingModel())

    fragments = list(adapter.stream("be helpful", [message(MessageRole.CUSTOMER, "Broken.")]))

    assert "".join(fragments) == "Is it lit?"


def test_stream_sends_the_system_prompt_first_then_the_turns_in_role_order() -> None:
    model = RecordingModel()
    adapter = LangChainChatModel(model)

    list(
        adapter.stream(
            "be helpful",
            [
                message(MessageRole.CUSTOMER, "Broken."),
                message(MessageRole.ASSISTANT, "Since when?"),
                message(MessageRole.CUSTOMER, "Today."),
            ],
        )
    )

    sent = model.streamed[0]
    assert isinstance(sent[0], SystemMessage)
    assert sent[0].content == "be helpful"
    assert [(type(m), m.content) for m in sent[1:]] == [
        (HumanMessage, "Broken."),
        (AIMessage, "Since when?"),
        (HumanMessage, "Today."),
    ]


def test_a_photo_message_becomes_image_blocks_before_its_text() -> None:
    store = FakePhotoStore()
    photo = Photo(
        id=uuid.uuid4(),
        filename="plate.jpg",
        media_type="image/jpeg",
        size_bytes=3,
        object_key="photos/p1",
        created_at=NOW,
    )
    store.put(preview_key(photo.object_key), b"tiny", "image/jpeg")
    model = RecordingModel()
    adapter = LangChainChatModel(model, photo_store=store)

    list(adapter.stream("sys", [message(MessageRole.CUSTOMER, "Here it is.", photos=(photo,))]))

    sent = model.streamed[0][1]
    assert sent.content == [
        {
            "type": "image",
            "source_type": "base64",
            "mime_type": "image/jpeg",
            "data": base64.b64encode(b"tiny").decode("ascii"),
        },
        {"type": "text", "text": "Here it is."},
    ]


def test_a_photo_only_message_has_no_text_block() -> None:
    """Anthropic rejects an empty text block, so a photo-only turn omits it entirely."""
    store = FakePhotoStore()
    photo = Photo(
        id=uuid.uuid4(),
        filename="plate.jpg",
        media_type="image/jpeg",
        size_bytes=3,
        object_key="photos/p1",
        created_at=NOW,
    )
    store.put(preview_key(photo.object_key), b"tiny", "image/jpeg")
    model = RecordingModel()
    adapter = LangChainChatModel(model, photo_store=store)

    list(adapter.stream("sys", [message(MessageRole.CUSTOMER, "", photos=(photo,))]))

    sent = model.streamed[0][1]
    assert sent.content == [
        {
            "type": "image",
            "source_type": "base64",
            "mime_type": "image/jpeg",
            "data": base64.b64encode(b"tiny").decode("ascii"),
        },
    ]


def test_a_plain_text_message_stays_a_plain_string() -> None:
    model = RecordingModel()
    adapter = LangChainChatModel(model, photo_store=FakePhotoStore())

    list(adapter.stream("sys", [message(MessageRole.CUSTOMER, "Broken.")]))

    sent = model.streamed[0][1]
    assert sent.content == "Broken."


def test_stream_forwards_only_the_text_blocks_of_a_multi_block_chunk() -> None:
    """Providers emit reasoning and tool-call blocks alongside text; only text is the reply."""
    model = RecordingModel(
        contents=[
            [
                {"type": "text", "text": "Check "},
                {"type": "thinking", "thinking": "the customer sounds unsure"},
            ],
            [{"type": "text", "text": "the breaker."}],
        ]
    )

    assert "".join(LangChainChatModel(model).stream("be helpful", [])) == "Check the breaker."


def test_stream_skips_chunks_that_carry_no_text() -> None:
    """A metadata-only chunk must not surface as an empty fragment in the customer's stream."""
    model = RecordingModel(contents=["Done", "", [{"type": "thinking", "thinking": "hmm"}], "!"])

    assert list(LangChainChatModel(model).stream("be helpful", [])) == ["Done", "!"]


def test_summarize_returns_the_port_dataclass() -> None:
    adapter = LangChainChatModel(RecordingModel())

    summary = adapter.summarize("summarize", [message(MessageRole.CUSTOMER, "Broken.")])

    assert isinstance(summary, TriageSummary)
    assert summary.equipment == "Oven"
    assert summary.problem_category == "Not heating"


def test_summarize_sends_the_system_prompt_then_the_exchange_as_one_labelled_transcript() -> None:
    model = RecordingModel()

    LangChainChatModel(model).summarize(
        "summarize",
        [
            message(MessageRole.CUSTOMER, "Broken."),
            message(MessageRole.ASSISTANT, "Since when?"),
        ],
    )

    sent = model.structured_input[0]
    assert [(type(m), m.content) for m in sent] == [
        (SystemMessage, "summarize"),
        (HumanMessage, "Customer: Broken.\n\nAssistant: Since when?"),
    ]


def test_summarize_renders_a_photo_only_turn_as_a_placeholder() -> None:
    photo = Photo(
        id=uuid.uuid4(),
        filename="plate.jpg",
        media_type="image/jpeg",
        size_bytes=3,
        object_key="photos/p1",
        created_at=NOW,
    )
    model = RecordingModel()

    LangChainChatModel(model).summarize(
        "summarize",
        [
            message(MessageRole.CUSTOMER, "", photos=(photo,)),
            message(MessageRole.ASSISTANT, "I see the leak."),
        ],
    )

    sent = model.structured_input[0]
    assert sent[1].content == "Customer: [photo]\n\nAssistant: I see the leak."


def test_summarize_does_not_end_the_request_on_an_assistant_turn() -> None:
    """The conversation being summarized always ends with the assistant's escalation reply, and a
    request ending on an assistant turn is a reply to prefill, which the provider rejects."""
    model = RecordingModel()

    LangChainChatModel(model).summarize(
        "summarize", [message(MessageRole.ASSISTANT, "I am booking a technician.")]
    )

    assert not isinstance(model.structured_input[0][-1], AIMessage)
