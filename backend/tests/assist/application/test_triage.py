"""Triage conversation orchestration: streaming turns and the three endings."""
from __future__ import annotations

import uuid
from collections.abc import Iterator, Sequence
from datetime import datetime, timedelta, timezone

import pytest

from fsm.assist.application.prompts import (
    CLOSED_MARKER,
    EQUIPMENT_CLOSE,
    EQUIPMENT_OPEN,
    ESCALATE_MARKER,
    QUESTION_CLOSE,
    QUESTION_OPEN,
    RESUME_MARKER,
    SKIP_MARKER,
    SOLVED_MARKER,
    SUMMARY_SYSTEM_PROMPT,
    TRIAGE_SYSTEM_PROMPT,
    QuestionSpan,
    build_summary_prompt,
)
from fsm.assist.application.triage import (
    GROUNDING_HITS,
    MAX_CUSTOMER_TURNS,
    TURN_CAP_HANDOFF,
    DocumentRef,
    TriageService,
    TurnOutcome,
    cited_sources,
)
from fsm.assist.domain.conversation import (
    CONVERSATION_TTL,
    Conversation,
    ConversationStatus,
    Message,
    MessageRole,
    Photo,
)
from fsm.assist.domain.document import ExtractedText
from fsm.assist.domain.errors import ConversationClosed, ConversationNotFound, PhotoNotFound
from fsm.assist.ports.document_index import SearchHit
from fsm.assist.ports.photo_repository import PhotoRepository
from fsm.assist.ports.photo_store import PhotoStore, photo_keys
from tests.assist.fakes import (
    FakeChatModel,
    FakeConversationRepository,
    FakeDocumentIndex,
    FakePhotoRepository,
    FakePhotoStore,
    FakeServiceCallOpener,
)

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)
CUSTOMER = uuid.uuid4()

OVEN_DOC = "The oven will not heat. Hold the reset button behind the lower panel for ten seconds."

LIFT = "Bruno VPL-3100 vertical platform lift"
LIFT_NAMED = f"That looks like a {EQUIPMENT_OPEN}{LIFT}{EQUIPMENT_CLOSE}."
ELEVATOR_NAMED = f"That looks like a {EQUIPMENT_OPEN}Savaria Eclipse home elevator{EQUIPMENT_CLOSE}."


class ExactFragmentChatModel(FakeChatModel):
    """Emits the given fragments verbatim, so a test can choose where the chunk boundaries fall."""

    def __init__(self, fragments: list[str]) -> None:
        super().__init__()
        self.fragments = fragments

    def stream(self, system: str, messages: Sequence[Message]) -> Iterator[str]:
        self.stream_calls.append((system, list(messages)))
        return iter(self.fragments)


class FailsWhenUnscriptedChatModel(FakeChatModel):
    """Streams the scripted replies, then fails partway, the way a dropped connection does."""

    def stream(self, system: str, messages: Sequence[Message]) -> Iterator[str]:
        if self.replies:
            yield from super().stream(system, messages)
            return
        self.stream_calls.append((system, list(messages)))
        yield "Let me check"
        raise RuntimeError("provider connection dropped")


class RecordingDocumentIndex(FakeDocumentIndex):
    """Records every search, so a test can assert what a turn asked the index for."""

    def __init__(self) -> None:
        super().__init__()
        self.searches: list[tuple[str, int]] = []

    def search(self, query: str, limit: int) -> list[SearchHit]:
        self.searches.append((query, limit))
        return super().search(query, limit)


class LosesTheStartRace(FakeConversationRepository):
    """Hides the winning conversation from the first read, the way an uncommitted insert does."""

    def __init__(self) -> None:
        super().__init__()
        self.reads = 0

    def find_active_for_customer(self, customer_id: uuid.UUID) -> Conversation | None:
        self.reads += 1
        if self.reads == 1:
            return None
        return super().find_active_for_customer(customer_id)


def make_service(
    *,
    replies: list[str] | None = None,
    now: datetime = NOW,
    photos: PhotoRepository | None = None,
    photo_store: PhotoStore | None = None,
) -> tuple[TriageService, FakeConversationRepository, FakeChatModel, FakeServiceCallOpener]:
    conversations = FakeConversationRepository()
    chat_model = FakeChatModel(replies=replies)
    openers = FakeServiceCallOpener()
    service = TriageService(
        conversations=conversations,
        chat_model=chat_model,
        service_calls=openers,
        clock=lambda: now,
        photos=photos,
        photo_store=photo_store,
    )
    return service, conversations, chat_model, openers


def drain(
    service: TriageService,
    conversation_id: uuid.UUID,
    text: str,
    photo_ids: Sequence[uuid.UUID] = (),
) -> str:
    return "".join(service.reply(conversation_id, CUSTOMER, text, photo_ids=photo_ids))


def make_photo(object_key: str = "photos/x") -> Photo:
    return Photo(
        id=uuid.uuid4(),
        filename="plate.jpg",
        media_type="image/jpeg",
        size_bytes=10,
        object_key=object_key,
        created_at=NOW,
    )


def store_photo_objects(photo_store: FakePhotoStore, photo: Photo) -> None:
    for key in photo_keys(photo.object_key):
        photo_store.put(key, b"content", photo.media_type)


def test_start_creates_an_active_conversation() -> None:
    service, conversations, _, _ = make_service()

    convo = service.start(CUSTOMER)

    assert convo.status is ConversationStatus.ACTIVE
    assert convo.customer_id == CUSTOMER
    assert convo.messages == []
    assert conversations.rows[convo.id] is convo


def test_start_returns_the_existing_active_conversation() -> None:
    service, _, _, _ = make_service()
    first = service.start(CUSTOMER)

    assert service.start(CUSTOMER).id == first.id


def test_start_abandons_an_expired_conversation_and_opens_a_new_one() -> None:
    service, conversations, _, _ = make_service()
    stale = service.start(CUSTOMER)

    later = NOW + CONVERSATION_TTL + timedelta(minutes=1)
    fresh_service = TriageService(
        conversations=conversations,
        chat_model=FakeChatModel(),
        service_calls=FakeServiceCallOpener(),
        clock=lambda: later,
    )
    fresh = fresh_service.start(CUSTOMER)

    assert fresh.id != stale.id
    assert conversations.rows[stale.id].status is ConversationStatus.ABANDONED


def test_start_does_not_reopen_another_customers_conversation() -> None:
    service, _, _, _ = make_service()
    mine = service.start(CUSTOMER)

    assert service.start(uuid.uuid4()).id != mine.id


def test_start_joins_the_conversation_that_won_a_concurrent_start() -> None:
    conversations = LosesTheStartRace()
    winner = Conversation(
        id=uuid.uuid4(),
        customer_id=CUSTOMER,
        status=ConversationStatus.ACTIVE,
        created_at=NOW,
        updated_at=NOW,
    )
    conversations.rows[winner.id] = winner
    service = TriageService(
        conversations=conversations,
        chat_model=FakeChatModel(),
        service_calls=FakeServiceCallOpener(),
        clock=lambda: NOW,
    )

    joined = service.start(CUSTOMER)

    assert joined.id == winner.id
    assert len(conversations.rows) == 1


def test_reply_streams_text_and_records_both_turns() -> None:
    service, conversations, _, _ = make_service(replies=["Is the display lit?"])
    convo = service.start(CUSTOMER)

    streamed = drain(service, convo.id, "The oven will not heat.")

    assert streamed.strip() == "Is the display lit?"
    stored = conversations.rows[convo.id]
    assert [(m.role, m.text) for m in stored.messages] == [
        (MessageRole.CUSTOMER, "The oven will not heat."),
        (MessageRole.ASSISTANT, "Is the display lit?"),
    ]


def test_reply_passes_the_full_history_to_the_model() -> None:
    service, _, chat_model, _ = make_service(replies=["One.", "Two."])
    convo = service.start(CUSTOMER)

    drain(service, convo.id, "First problem.")
    drain(service, convo.id, "Second detail.")

    _, second_call_messages = chat_model.stream_calls[1]
    assert [m.text for m in second_call_messages] == [
        "First problem.",
        "One.",
        "Second detail.",
    ]


def test_solved_marker_closes_the_conversation_without_a_service_call() -> None:
    service, conversations, _, openers = make_service(
        replies=[f"Glad that fixed it. {SOLVED_MARKER}"]
    )
    convo = service.start(CUSTOMER)

    streamed = drain(service, convo.id, "That worked, thanks.")

    assert SOLVED_MARKER not in streamed
    assert streamed.strip() == "Glad that fixed it."
    assert conversations.rows[convo.id].status is ConversationStatus.SOLVED
    assert openers.opened == []
    assert service.outcome().status is ConversationStatus.SOLVED
    assert service.outcome().service_call_id is None


def test_escalate_marker_opens_a_service_call_carrying_the_summary() -> None:
    service, conversations, chat_model, openers = make_service(
        replies=[f"I will book a technician. {ESCALATE_MARKER}"]
    )
    convo = service.start(CUSTOMER)

    streamed = drain(service, convo.id, "Still cold after all that.")

    assert ESCALATE_MARKER not in streamed
    stored = conversations.rows[convo.id]
    assert stored.status is ConversationStatus.ESCALATED
    assert len(openers.opened) == 1
    opened = openers.opened[0]
    assert stored.service_call_id == opened.id
    assert opened.description == chat_model.summary.render()
    assert service.outcome().service_call_id == opened.id
    assert service.outcome().service_call_description == opened.description



def test_escalation_hands_the_opener_the_summary_it_wrote() -> None:
    """The service call keeps the structure, so no surface has to read it back out of the text."""
    service, _, chat_model, openers = make_service(
        replies=[f"I will book a technician. {ESCALATE_MARKER}"]
    )
    convo = service.start(CUSTOMER)

    drain(service, convo.id, "Still cold after all that.")

    assert openers.opened_summaries[0] == chat_model.summary


def test_closed_marker_abandons_the_conversation_without_a_service_call() -> None:
    service, conversations, chat_model, openers = make_service(
        replies=[f"That is outside what I can help with. {CLOSED_MARKER}"]
    )
    convo = service.start(CUSTOMER)

    streamed = drain(service, convo.id, "Please close this chat.")

    assert CLOSED_MARKER not in streamed
    assert streamed.strip() == "That is outside what I can help with."
    assert conversations.rows[convo.id].status is ConversationStatus.ABANDONED
    assert conversations.rows[convo.id].service_call_id is None
    assert openers.opened == []
    assert chat_model.summarize_calls == []
    assert service.outcome() == TurnOutcome(status=ConversationStatus.ABANDONED)


def test_a_wrapped_question_reports_its_span_and_keeps_the_conversation_active() -> None:
    service, conversations, _, openers = make_service(
        replies=[f"Power is fine. {QUESTION_OPEN}Is the breaker on?{QUESTION_CLOSE}"]
    )
    convo = service.start(CUSTOMER)

    fragments = list(service.reply(convo.id, CUSTOMER, "The oven will not heat."))

    assert all("[[" not in fragment for fragment in fragments)
    answer = "".join(fragments).strip()
    assert answer == "Power is fine. Is the breaker on?"
    stored = conversations.rows[convo.id]
    assert stored.status is ConversationStatus.ACTIVE
    assert stored.messages[-1].text == answer
    assert openers.opened == []
    outcome = service.outcome()
    assert outcome == TurnOutcome(
        status=ConversationStatus.ACTIVE, question=QuestionSpan(15, 33)
    )
    assert answer[outcome.question.start:outcome.question.end] == "Is the breaker on?"


def test_the_question_streams_out_before_its_closing_delimiter_arrives() -> None:
    """The wrapper sits mid-reply, so holding back from it would stall most of the message."""
    conversations = FakeConversationRepository()
    service = TriageService(
        conversations=conversations,
        chat_model=ExactFragmentChatModel(
            ["Power is fine. ", QUESTION_OPEN, "Is the breaker", " on?", QUESTION_CLOSE]
        ),
        service_calls=FakeServiceCallOpener(),
        clock=lambda: NOW,
    )
    convo = service.start(CUSTOMER)

    fragments = [f for f in service.reply(convo.id, CUSTOMER, "It will not heat.") if f]

    assert "".join(fragments) == "Power is fine. Is the breaker on?"
    # The question reached the customer while the closing delimiter was still unwritten.
    assert "Is the breaker" in "".join(fragments[:-1])
    assert service.outcome().question == QuestionSpan(15, 33)


def test_an_open_question_reports_no_span() -> None:
    service, _, _, _ = make_service(replies=["What is the model number?"])
    convo = service.start(CUSTOMER)

    drain(service, convo.id, "The oven will not heat.")

    assert service.outcome().question is None


def test_end_abandons_an_open_conversation() -> None:
    service, conversations, _, openers = make_service()
    convo = service.start(CUSTOMER)

    ended = service.end(convo.id, CUSTOMER)

    assert ended.status is ConversationStatus.ABANDONED
    assert conversations.rows[convo.id].status is ConversationStatus.ABANDONED
    assert openers.opened == []


def test_end_rejects_a_conversation_that_has_already_ended() -> None:
    service, _, _, _ = make_service(replies=[f"Glad that fixed it. {SOLVED_MARKER}"])
    convo = service.start(CUSTOMER)
    drain(service, convo.id, "That worked, thanks.")

    with pytest.raises(ConversationClosed):
        service.end(convo.id, CUSTOMER)


def test_end_rejects_a_conversation_the_caller_does_not_own() -> None:
    service, conversations, _, _ = make_service()
    convo = service.start(CUSTOMER)

    with pytest.raises(ConversationNotFound):
        service.end(convo.id, uuid.uuid4())

    assert conversations.rows[convo.id].status is ConversationStatus.ACTIVE


def test_summarize_sees_the_whole_conversation_including_the_final_turn() -> None:
    service, _, chat_model, _ = make_service(replies=[f"Booking a visit. {ESCALATE_MARKER}"])
    convo = service.start(CUSTOMER)

    drain(service, convo.id, "Still cold.")

    _, summarized = chat_model.summarize_calls[0]
    assert [m.text for m in summarized] == ["Still cold.", "Booking a visit."]


def test_reply_to_a_closed_conversation_is_rejected_before_the_model_is_called() -> None:
    service, _, chat_model, _ = make_service(replies=[f"Done. {SOLVED_MARKER}"])
    convo = service.start(CUSTOMER)
    drain(service, convo.id, "Fixed it.")
    calls_before = len(chat_model.stream_calls)

    with pytest.raises(ConversationClosed):
        drain(service, convo.id, "One more thing.")

    assert len(chat_model.stream_calls) == calls_before


def test_reply_to_another_customers_conversation_is_rejected() -> None:
    service, _, _, _ = make_service()
    convo = service.start(CUSTOMER)

    with pytest.raises(ConversationNotFound):
        "".join(service.reply(convo.id, uuid.uuid4(), "Let me in."))


def test_get_returns_the_conversation_for_its_owner() -> None:
    service, _, _, _ = make_service()
    convo = service.start(CUSTOMER)

    assert service.get(convo.id, CUSTOMER).id == convo.id


def test_get_rejects_a_conversation_the_caller_does_not_own() -> None:
    service, _, _, _ = make_service()
    convo = service.start(CUSTOMER)

    with pytest.raises(ConversationNotFound):
        service.get(convo.id, uuid.uuid4())


def test_marker_never_appears_in_the_streamed_fragments() -> None:
    service, _, _, _ = make_service(replies=[f"All set. {SOLVED_MARKER}"])
    convo = service.start(CUSTOMER)

    fragments = list(service.reply(convo.id, CUSTOMER, "Fixed."))

    assert all("[[" not in fragment for fragment in fragments)
    assert "".join(fragments).strip() == "All set."


def test_nothing_is_persisted_when_the_stream_is_abandoned() -> None:
    service, conversations, _, _ = make_service(replies=["Is the display lit?"])
    convo = service.start(CUSTOMER)

    stream = service.reply(convo.id, CUSTOMER, "It will not heat.")
    next(stream)
    stream.close()

    assert conversations.rows[convo.id].messages == []


def test_a_held_back_tail_survives_a_reply_that_opens_with_whitespace() -> None:
    conversations = FakeConversationRepository()
    service = TriageService(
        conversations=conversations,
        chat_model=ExactFragmentChatModel(["  hello", " world["]),
        service_calls=FakeServiceCallOpener(),
        clock=lambda: NOW,
    )
    convo = service.start(CUSTOMER)

    streamed = drain(service, convo.id, "Hello?")

    assert streamed == "hello world["
    assert conversations.rows[convo.id].messages[-1].text == streamed


def test_turns_below_the_cap_stay_with_the_model() -> None:
    service, conversations, chat_model, openers = make_service()
    convo = service.start(CUSTOMER)

    for turn in range(MAX_CUSTOMER_TURNS - 1):
        drain(service, convo.id, f"Detail {turn}.")

    assert len(chat_model.stream_calls) == MAX_CUSTOMER_TURNS - 1
    assert conversations.rows[convo.id].status is ConversationStatus.ACTIVE
    assert openers.opened == []


def test_the_turn_cap_escalates_instead_of_asking_the_model_again() -> None:
    service, conversations, chat_model, openers = make_service()
    convo = service.start(CUSTOMER)
    for turn in range(MAX_CUSTOMER_TURNS - 1):
        drain(service, convo.id, f"Detail {turn}.")
    streams_before = len(chat_model.stream_calls)

    streamed = drain(service, convo.id, "Still not fixed.")

    assert streamed == TURN_CAP_HANDOFF
    assert len(chat_model.stream_calls) == streams_before
    assert conversations.rows[convo.id].status is ConversationStatus.ESCALATED


def test_the_forced_escalation_opens_a_service_call_carrying_the_summary() -> None:
    service, conversations, chat_model, openers = make_service()
    convo = service.start(CUSTOMER)
    for turn in range(MAX_CUSTOMER_TURNS - 1):
        drain(service, convo.id, f"Detail {turn}.")

    drain(service, convo.id, "Still not fixed.")

    assert len(openers.opened) == 1
    opened = openers.opened[0]
    assert opened.description == chat_model.summary.render()
    assert conversations.rows[convo.id].service_call_id == opened.id
    assert service.outcome().service_call_id == opened.id
    assert service.outcome().service_call_description == opened.description
    _, summarized = chat_model.summarize_calls[0]
    assert [m.text for m in summarized[-2:]] == ["Still not fixed.", TURN_CAP_HANDOFF]


def make_grounded_service(
    document_index: FakeDocumentIndex | None,
    replies: list[str] | None = None,
) -> tuple[TriageService, FakeChatModel]:
    chat_model = FakeChatModel(replies=replies)
    service = TriageService(
        conversations=FakeConversationRepository(),
        chat_model=chat_model,
        service_calls=FakeServiceCallOpener(),
        document_index=document_index,
        clock=lambda: NOW,
    )
    return service, chat_model


def test_a_turn_searches_the_index_with_the_customers_own_words() -> None:
    index = RecordingDocumentIndex()
    service, _ = make_grounded_service(index)
    convo = service.start(CUSTOMER)

    drain(service, convo.id, "The oven will not heat.")

    assert index.searches == [("The oven will not heat.", GROUNDING_HITS)]


def test_a_matching_document_reaches_the_model_as_prompt_material() -> None:
    index = FakeDocumentIndex()
    index.index_document(uuid.uuid4(), "oven-guide.md", ExtractedText(text=OVEN_DOC))
    service, chat_model = make_grounded_service(index)
    convo = service.start(CUSTOMER)

    drain(service, convo.id, "The oven will not heat.")

    system, _ = chat_model.stream_calls[0]
    assert "oven-guide.md" in system
    assert OVEN_DOC in system


def test_every_turn_searches_again_so_the_topic_can_move_mid_conversation() -> None:
    index = RecordingDocumentIndex()
    service, _ = make_grounded_service(index)
    convo = service.start(CUSTOMER)

    drain(service, convo.id, "The oven will not heat.")
    drain(service, convo.id, "Now the fridge is making a noise.")

    assert [query for query, _ in index.searches] == [
        "The oven will not heat.",
        "Now the fridge is making a noise.",
    ]


def test_a_later_turn_searches_with_the_equipment_the_assistant_identified() -> None:
    """A follow-up leaves its subject to the conversation, so the query has to supply it."""
    index = RecordingDocumentIndex()
    service, _ = make_grounded_service(index, replies=[f"{LIFT_NAMED} Is the gate latched?"])
    convo = service.start(CUSTOMER)
    drain(service, convo.id, "My lift stopped working.")

    drain(service, convo.id, "What are the dimensions?")

    assert [query for query, _ in index.searches] == [
        "My lift stopped working.",
        f"{LIFT}\nWhat are the dimensions?",
    ]


def test_a_corrected_identity_is_what_later_turns_search_with() -> None:
    index = RecordingDocumentIndex()
    service, _ = make_grounded_service(
        index,
        replies=[ELEVATOR_NAMED, f"{LIFT_NAMED} The rating plate settles it."],
    )
    convo = service.start(CUSTOMER)
    drain(service, convo.id, "It will not move.")
    drain(service, convo.id, "Here is the rating plate.")

    drain(service, convo.id, "What are the dimensions?")

    assert index.searches[-1][0] == f"{LIFT}\nWhat are the dimensions?"


def test_the_identity_reaches_the_conversation_and_its_name_reaches_the_customer() -> None:
    service, conversations, _, _ = make_service(
        replies=[f"That looks like a {EQUIPMENT_OPEN}{LIFT}{EQUIPMENT_CLOSE} to me."]
    )
    convo = service.start(CUSTOMER)

    streamed = drain(service, convo.id, "My lift stopped working.")

    assert conversations.rows[convo.id].equipment == LIFT
    assert EQUIPMENT_OPEN not in streamed
    assert EQUIPMENT_CLOSE not in streamed
    assert streamed.strip() == f"That looks like a {LIFT} to me."
    assert conversations.rows[convo.id].messages[-1].text == f"That looks like a {LIFT} to me."


def test_a_skip_request_flips_the_conversation_into_the_declined_regime() -> None:
    """The customer's request must outlive the turn that voiced it, so a retried or drifting later
    turn is still told not to troubleshoot."""
    service, conversations, chat_model, _ = make_service(
        replies=[f"Understood — what is the equipment?\n{SKIP_MARKER}", "Noted."]
    )
    convo = service.start(CUSTOMER)

    streamed = drain(service, convo.id, "Open a service call. I don't want to triage.")

    assert SKIP_MARKER not in streamed
    assert conversations.rows[convo.id].triage_declined is True
    assert conversations.rows[convo.id].status is ConversationStatus.ACTIVE
    assert "already agreed to a service call" not in chat_model.stream_calls[0][0]

    drain(service, convo.id, "It is the porch lift.")

    assert "already agreed to a service call" in chat_model.stream_calls[1][0]


def test_a_resume_returns_a_declined_conversation_to_normal_triage() -> None:
    service, conversations, chat_model, _ = make_service(
        replies=[
            f"Understood.\n{SKIP_MARKER}",
            f"Happy to try. {RESUME_MARKER}Is the display lit?",
            "Tell me more.",
        ]
    )
    convo = service.start(CUSTOMER)
    drain(service, convo.id, "Just open a call.")

    streamed = drain(service, convo.id, "Actually, let's try fixing it first.")

    assert RESUME_MARKER not in streamed
    assert conversations.rows[convo.id].triage_declined is False

    drain(service, convo.id, "Sure.")

    assert "already agreed to a service call" not in chat_model.stream_calls[2][0]


def test_a_skip_with_the_equipment_already_known_escalates_in_the_same_turn() -> None:
    service, conversations, _, openers = make_service(
        replies=[f"Opening the call now.\n{SKIP_MARKER}\n{ESCALATE_MARKER}"]
    )
    convo = service.start(CUSTOMER)

    drain(service, convo.id, "Skip the questions — my porch lift will not move at all.")

    assert conversations.rows[convo.id].status is ConversationStatus.ESCALATED
    assert conversations.rows[convo.id].triage_declined is True
    assert len(openers.opened) == 1


def test_the_escalation_summary_is_told_what_triage_identified() -> None:
    service, _, chat_model, _ = make_service(
        replies=[LIFT_NAMED, f"Opening a service call. {ESCALATE_MARKER}"]
    )
    convo = service.start(CUSTOMER)
    drain(service, convo.id, "It will not move.")

    drain(service, convo.id, "Yes, book a visit.")

    system, _ = chat_model.summarize_calls[0]
    assert system == build_summary_prompt(LIFT)


def test_a_conversation_that_never_identified_the_equipment_summarizes_from_the_transcript() -> None:
    service, _, chat_model, _ = make_service(replies=[f"Opening a service call. {ESCALATE_MARKER}"])
    convo = service.start(CUSTOMER)

    drain(service, convo.id, "Yes, book a visit.")

    system, _ = chat_model.summarize_calls[0]
    assert system == SUMMARY_SYSTEM_PROMPT


def test_a_search_that_matches_nothing_leaves_the_model_on_the_bare_prompt() -> None:
    index = FakeDocumentIndex()
    index.index_document(uuid.uuid4(), "oven-guide.md", ExtractedText(text=OVEN_DOC))
    service, chat_model = make_grounded_service(index)
    convo = service.start(CUSTOMER)

    drain(service, convo.id, "The washing machine door is jammed.")

    system, _ = chat_model.stream_calls[0]
    assert system == TRIAGE_SYSTEM_PROMPT


def test_triage_runs_unchanged_when_no_index_is_configured() -> None:
    service, chat_model = make_grounded_service(None)
    convo = service.start(CUSTOMER)

    streamed = drain(service, convo.id, "The oven will not heat.")

    system, _ = chat_model.stream_calls[0]
    assert system == TRIAGE_SYSTEM_PROMPT
    assert streamed.strip() == "Tell me more about the problem."


def test_the_turn_cap_escalates_without_spending_a_search() -> None:
    index = RecordingDocumentIndex()
    service, _ = make_grounded_service(index)
    convo = service.start(CUSTOMER)
    for turn in range(MAX_CUSTOMER_TURNS - 1):
        drain(service, convo.id, f"Detail {turn}.")
    searches_before = len(index.searches)

    drain(service, convo.id, "Still not fixed.")

    assert len(index.searches) == searches_before


def test_outcome_does_not_carry_the_previous_turns_ending_into_a_failed_turn() -> None:
    conversations = FakeConversationRepository()
    service = TriageService(
        conversations=conversations,
        chat_model=FailsWhenUnscriptedChatModel(replies=[f"Booking a visit. {ESCALATE_MARKER}"]),
        service_calls=FakeServiceCallOpener(),
        clock=lambda: NOW,
    )
    first = service.start(CUSTOMER)
    drain(service, first.id, "Still cold.")
    assert service.outcome().status is ConversationStatus.ESCALATED

    second = service.start(CUSTOMER)
    with pytest.raises(RuntimeError):
        drain(service, second.id, "A different problem.")

    assert service.outcome() == TurnOutcome(status=ConversationStatus.ACTIVE)


def test_a_photo_turn_reaches_the_model_on_the_customer_message(
    fake_photo_repo: FakePhotoRepository, fake_photo_store: FakePhotoStore
) -> None:
    service, _, chat_model, _ = make_service(
        replies=["Can you tell me more?"], photos=fake_photo_repo, photo_store=fake_photo_store
    )
    convo = service.start(CUSTOMER)
    photo = make_photo()
    fake_photo_repo.add(convo.id, photo)

    drain(service, convo.id, "Here is a photo.", photo_ids=[photo.id])

    _, history = chat_model.stream_calls[-1]
    last_customer_message = next(m for m in reversed(history) if m.role is MessageRole.CUSTOMER)
    assert last_customer_message.photos == (photo,)
    assert photo.id in fake_photo_repo.bound


def test_a_bound_photo_cannot_be_sent_twice(
    fake_photo_repo: FakePhotoRepository, fake_photo_store: FakePhotoStore
) -> None:
    service, _, _, _ = make_service(
        replies=["Can you tell me more?", "Anything else?"],
        photos=fake_photo_repo,
        photo_store=fake_photo_store,
    )
    convo = service.start(CUSTOMER)
    photo = make_photo()
    fake_photo_repo.add(convo.id, photo)
    drain(service, convo.id, "Here is a photo.", photo_ids=[photo.id])

    with pytest.raises(PhotoNotFound):
        drain(service, convo.id, "Here it is again.", photo_ids=[photo.id])


def test_a_solved_conversation_leaves_no_objects_behind(
    fake_photo_repo: FakePhotoRepository, fake_photo_store: FakePhotoStore
) -> None:
    service, _, _, _ = make_service(
        replies=["Try this.", f"Glad that fixed it. {SOLVED_MARKER}"],
        photos=fake_photo_repo,
        photo_store=fake_photo_store,
    )
    convo = service.start(CUSTOMER)
    sent_photo = make_photo("photos/sent")
    unbound_photo = make_photo("photos/unbound")
    fake_photo_repo.add(convo.id, sent_photo)
    fake_photo_repo.add(convo.id, unbound_photo)
    store_photo_objects(fake_photo_store, sent_photo)
    store_photo_objects(fake_photo_store, unbound_photo)
    drain(service, convo.id, "Here is a photo.", photo_ids=[sent_photo.id])

    drain(service, convo.id, "That worked, thanks.")
    service.remove_discarded_objects()

    assert fake_photo_store.objects == {}
    assert fake_photo_repo.list_unbound(convo.id) == []
    assert sent_photo.id in fake_photo_repo.rows
    assert unbound_photo.id not in fake_photo_repo.rows


def test_customer_end_discards_the_conversations_objects(
    fake_photo_repo: FakePhotoRepository, fake_photo_store: FakePhotoStore
) -> None:
    service, _, _, _ = make_service(
        replies=["Try this."], photos=fake_photo_repo, photo_store=fake_photo_store
    )
    convo = service.start(CUSTOMER)
    sent_photo = make_photo("photos/sent")
    unbound_photo = make_photo("photos/unbound")
    fake_photo_repo.add(convo.id, sent_photo)
    fake_photo_repo.add(convo.id, unbound_photo)
    store_photo_objects(fake_photo_store, sent_photo)
    store_photo_objects(fake_photo_store, unbound_photo)
    drain(service, convo.id, "Here is a photo.", photo_ids=[sent_photo.id])

    service.end(convo.id, CUSTOMER)
    service.remove_discarded_objects()

    assert fake_photo_store.objects == {}


def test_an_ending_removes_objects_only_when_the_caller_confirms_the_commit(
    fake_photo_repo: FakePhotoRepository, fake_photo_store: FakePhotoStore
) -> None:
    """An ending stages its object removals for the caller to flush after the transaction
    commits; removing inline would let a failed commit leave a still-ACTIVE conversation
    whose images are already gone."""
    service, _, _, _ = make_service(
        replies=[f"Glad that fixed it. {SOLVED_MARKER}"],
        photos=fake_photo_repo,
        photo_store=fake_photo_store,
    )
    convo = service.start(CUSTOMER)
    photo = make_photo()
    fake_photo_repo.add(convo.id, photo)
    store_photo_objects(fake_photo_store, photo)

    drain(service, convo.id, "That worked, thanks.", photo_ids=[photo.id])

    assert set(fake_photo_store.objects) == set(photo_keys(photo.object_key))

    service.remove_discarded_objects()

    assert fake_photo_store.objects == {}


def test_escalation_hands_the_sent_photos_to_the_opener_and_keeps_their_objects(
    fake_photo_repo: FakePhotoRepository, fake_photo_store: FakePhotoStore
) -> None:
    service, _, _, openers = make_service(
        replies=["Try this.", f"I will book a technician. {ESCALATE_MARKER}"],
        photos=fake_photo_repo,
        photo_store=fake_photo_store,
    )
    convo = service.start(CUSTOMER)
    sent_photo = make_photo("photos/sent")
    unbound_photo = make_photo("photos/unbound")
    fake_photo_repo.add(convo.id, sent_photo)
    fake_photo_repo.add(convo.id, unbound_photo)
    store_photo_objects(fake_photo_store, sent_photo)
    store_photo_objects(fake_photo_store, unbound_photo)
    drain(service, convo.id, "Here is a photo.", photo_ids=[sent_photo.id])

    drain(service, convo.id, "Still cold after all that.")
    service.remove_discarded_objects()

    assert openers.opened_photos[-1] == [sent_photo]
    for key in photo_keys(sent_photo.object_key):
        assert key in fake_photo_store.objects
    for key in photo_keys(unbound_photo.object_key):
        assert key not in fake_photo_store.objects
    assert sent_photo.id in fake_photo_repo.rows
    assert unbound_photo.id not in fake_photo_repo.rows


def test_the_turn_cap_escalation_carries_a_sent_photo_to_the_opener(
    fake_photo_repo: FakePhotoRepository, fake_photo_store: FakePhotoStore
) -> None:
    service, _, _, openers = make_service(photos=fake_photo_repo, photo_store=fake_photo_store)
    convo = service.start(CUSTOMER)
    for turn in range(MAX_CUSTOMER_TURNS - 1):
        drain(service, convo.id, f"Detail {turn}.")
    photo = make_photo()
    fake_photo_repo.add(convo.id, photo)

    drain(service, convo.id, "Still not fixed.", photo_ids=[photo.id])

    assert openers.opened_photos[-1] == [photo]


DOC_A = uuid.uuid4()
DOC_B = uuid.uuid4()


def hit(document_id: uuid.UUID, filename: str, score: float) -> SearchHit:
    return SearchHit(document_id=document_id, filename=filename, content="…", score=score)


class ScoredIndex(FakeDocumentIndex):
    """Returns hits with the scores a test names, standing in for a real similarity search."""

    def __init__(self, hits: list[SearchHit]) -> None:
        super().__init__()
        self.hits = hits

    def search(self, query: str, limit: int) -> list[SearchHit]:
        return self.hits[:limit]


def test_a_document_matching_on_a_cluster_of_chunks_is_offered_as_a_source() -> None:
    assert cited_sources(
        [hit(DOC_A, "elevators.pdf", 0.55), hit(DOC_A, "elevators.pdf", 0.48)]
    ) == (DocumentRef(id=DOC_A, filename="elevators.pdf"),)


def test_a_document_matching_on_one_chunk_alone_is_not_offered() -> None:
    assert cited_sources([hit(DOC_A, "elevators.pdf", 0.55), hit(DOC_B, "ovens.pdf", 0.50)]) == ()


def test_chunks_below_the_score_do_not_count_towards_the_cluster() -> None:
    assert cited_sources(
        [hit(DOC_A, "elevators.pdf", 0.55), hit(DOC_A, "elevators.pdf", 0.44)]
    ) == ()


def test_a_search_that_matched_nothing_well_offers_no_source() -> None:
    assert cited_sources([hit(DOC_A, "elevators.pdf", 0.24)] * 3) == ()


def test_qualifying_documents_are_offered_best_match_first() -> None:
    sources = cited_sources(
        [
            hit(DOC_A, "elevators.pdf", 0.50),
            hit(DOC_A, "elevators.pdf", 0.49),
            hit(DOC_B, "ovens.pdf", 0.60),
            hit(DOC_B, "ovens.pdf", 0.46),
        ]
    )
    assert [source.filename for source in sources] == ["ovens.pdf", "elevators.pdf"]


def test_a_turn_reports_the_documents_it_matched_on_its_outcome() -> None:
    index = ScoredIndex([hit(DOC_A, "elevators.pdf", 0.55), hit(DOC_A, "elevators.pdf", 0.48)])
    service, _ = make_grounded_service(index)
    convo = service.start(CUSTOMER)

    drain(service, convo.id, "The lift doors keep bouncing open.")

    assert service.outcome().sources == (DocumentRef(id=DOC_A, filename="elevators.pdf"),)


def test_a_turn_that_matched_nothing_well_reports_no_documents() -> None:
    index = ScoredIndex([hit(DOC_A, "elevators.pdf", 0.24), hit(DOC_A, "elevators.pdf", 0.22)])
    service, _ = make_grounded_service(index)
    convo = service.start(CUSTOMER)

    drain(service, convo.id, "What time does the office open?")

    assert service.outcome().sources == ()


def test_the_next_turn_replaces_the_previous_turns_documents() -> None:
    index = ScoredIndex([hit(DOC_A, "elevators.pdf", 0.55), hit(DOC_A, "elevators.pdf", 0.48)])
    service, _ = make_grounded_service(index)
    convo = service.start(CUSTOMER)
    drain(service, convo.id, "The lift doors keep bouncing open.")

    index.hits = [hit(DOC_A, "elevators.pdf", 0.24)]
    drain(service, convo.id, "Never mind, what time does the office open?")

    assert service.outcome().sources == ()


def test_the_offered_page_is_where_the_best_matching_passage_starts() -> None:
    sources = cited_sources(
        [
            SearchHit(document_id=DOC_A, filename="elevators.pdf", content="…", score=0.48,
                      page=12),
            SearchHit(document_id=DOC_A, filename="elevators.pdf", content="…", score=0.55,
                      page=213),
        ]
    )

    assert sources == (DocumentRef(id=DOC_A, filename="elevators.pdf", page=213),)


def test_a_document_indexed_without_pages_is_offered_without_one() -> None:
    sources = cited_sources([hit(DOC_A, "notes.md", 0.55), hit(DOC_A, "notes.md", 0.48)])

    assert sources == (DocumentRef(id=DOC_A, filename="notes.md", page=None),)
