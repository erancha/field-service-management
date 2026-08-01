"""Triage conversation orchestration: streaming turns and the three endings."""
from __future__ import annotations

import uuid
from collections.abc import Iterator, Sequence
from datetime import datetime, timedelta, timezone

import pytest

from fsm.assist.application.prompts import (
    CLOSED_MARKER,
    ESCALATE_MARKER,
    QUESTION_CLOSE,
    QUESTION_OPEN,
    SOLVED_MARKER,
    TRIAGE_SYSTEM_PROMPT,
    QuestionSpan,
)
from fsm.assist.application.triage import (
    GROUNDING_HITS,
    MAX_CUSTOMER_TURNS,
    TURN_CAP_HANDOFF,
    TriageService,
    TurnOutcome,
)
from fsm.assist.domain.conversation import (
    CONVERSATION_TTL,
    Conversation,
    ConversationStatus,
    Message,
    MessageRole,
    Photo,
)
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
) -> tuple[TriageService, FakeChatModel]:
    chat_model = FakeChatModel()
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
    index.index_document(uuid.uuid4(), "oven-guide.md", OVEN_DOC)
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


def test_a_search_that_matches_nothing_leaves_the_model_on_the_bare_prompt() -> None:
    index = FakeDocumentIndex()
    index.index_document(uuid.uuid4(), "oven-guide.md", OVEN_DOC)
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
