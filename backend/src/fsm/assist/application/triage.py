"""Runs the customer triage conversation and its three endings."""
from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from fsm.assist.application.prompts import (
    CLOSED_MARKER,
    ESCALATE_MARKER,
    MARKERS,
    SOLVED_MARKER,
    SUMMARY_SYSTEM_PROMPT,
    ParsedReply,
    QuestionSpan,
    build_system_prompt,
    parse_reply,
)
from fsm.assist.domain.conversation import (
    Conversation,
    ConversationStatus,
    ConversationSummary,
    Message,
    MessageRole,
    Photo,
)
from fsm.assist.domain.errors import ConversationAlreadyOpen
from fsm.assist.ports.chat_model import ChatModel
from fsm.assist.ports.conversation_repository import ConversationRepository
from fsm.assist.ports.document_index import DocumentIndex
from fsm.assist.ports.photo_repository import PhotoRepository
from fsm.assist.ports.photo_store import PhotoStore, photo_keys
from fsm.assist.ports.service_calls import ServiceCallOpener


MAX_CUSTOMER_TURNS = 12
"""How many customer messages one conversation carries before triage hands off to a technician.

Every turn re-sends the whole exchange, so spend grows with the square of the length and a long
enough history overruns the model's context window, after which no further turn can succeed. The
cap escalates instead of refusing: a customer still stuck after this many turns needs a visit, and
an open service call is the safe direction to fail in.
"""

HISTORY_LENGTH = 20
"""How many past conversations the customer's history list carries.

The list is a way back to a recent exchange, not an archive, and it is fetched whole with no
paging; a customer with a long history sees the newest conversations and no control to reach
further back.
"""

GROUNDING_HITS = 3
"""Chunks retrieved per turn to ground the reply.

Retrieval runs on every turn rather than once, since the topic can move within a conversation. The
count stays small because each hit's full chunk text goes into the system prompt.
"""

TURN_CAP_HANDOFF = (
    "We have worked through a fair few things without getting this sorted, so I am opening a "
    "service call for a technician to take a proper look. You will be asked to pick a visit slot "
    "next."
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class TurnOutcome:
    """How the conversation stands after a turn; the escalation fields are set only on escalation.

    question is how the chat surface learns, without inspecting the reply text, both that the turn
    asked a plain yes/no question it can offer Yes/No buttons for, and where that question sits in
    the reply so it can be emphasised.
    """

    status: ConversationStatus
    service_call_id: uuid.UUID | None = None
    service_call_description: str | None = None
    question: QuestionSpan | None = None


def _visible_prefix(text: str) -> str:
    """What of a part-streamed reply the customer can be shown now.

    Complete markers are cut out where they stand, because the question delimiters sit mid-reply:
    withholding everything from the first marker onward would stall the bulk of the message until
    the stream ended. Any tail that is still only a prefix of a marker is withheld until the stream
    resolves whether it becomes one.

    Successive calls return successively longer text — a withheld tail either completes into a
    marker that is removed, or turns out to be ordinary text that is then released — so the caller
    can treat what it has already emitted as a prefix of what this returns.
    """
    limit = len(text)
    for marker in MARKERS:
        for length in range(1, len(marker)):
            if text.endswith(marker[:length]):
                limit = min(limit, len(text) - length)
    visible = text[:limit]
    for marker in MARKERS:
        visible = visible.replace(marker, "")
    return visible


class TriageService:
    """One conversation per customer at a time, ending solved, escalated, or abandoned."""

    def __init__(
        self,
        conversations: ConversationRepository,
        chat_model: ChatModel,
        service_calls: ServiceCallOpener,
        *,
        document_index: DocumentIndex | None = None,
        clock: Callable[[], datetime] = _utc_now,
        id_factory: Callable[[], uuid.UUID] = uuid.uuid4,
        photos: PhotoRepository | None = None,
        photo_store: PhotoStore | None = None,
    ) -> None:
        self._conversations = conversations
        self._chat_model = chat_model
        self._service_calls = service_calls
        self._document_index = document_index
        self._clock = clock
        self._new_id = id_factory
        self._photos = photos
        self._photo_store = photo_store
        self._outcome = TurnOutcome(status=ConversationStatus.ACTIVE)
        # Object keys an ending has discarded; their store deletion is deferred until the
        # transaction that recorded the ending has committed.
        self._discarded_keys: list[str] = []

    def start(self, customer_id: uuid.UUID) -> Conversation:
        """The customer's open conversation, retiring one they walked away from.

        Looking for an existing conversation cannot see one another request is still committing, so
        two concurrent starts both reach the insert and the store rejects the loser. The loser joins
        the winner's conversation, which is the single thread the customer expects either way.
        """
        now = self._clock()
        existing = self._conversations.find_active_for_customer(customer_id)
        if existing is not None:
            if not existing.is_expired(now):
                return existing
            existing.mark_abandoned(now)
            self._conversations.save(existing)
            self._discard_photos(existing)

        conversation = Conversation(
            id=self._new_id(),
            customer_id=customer_id,
            status=ConversationStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        try:
            self._conversations.add(conversation)
        except ConversationAlreadyOpen:
            winner = self._conversations.find_active_for_customer(customer_id)
            if winner is None:
                raise
            return winner
        return conversation

    def get(self, conversation_id: uuid.UUID, customer_id: uuid.UUID) -> Conversation:
        return self._conversations.get(conversation_id, customer_id)

    def end(self, conversation_id: uuid.UUID, customer_id: uuid.UUID) -> Conversation:
        """Close the conversation at the customer's own request, booking nothing.

        This is the exit that does not depend on the model writing an ending marker, and it lands
        on the same abandonment the marker does, so an ended conversation reads the same either way.
        """
        conversation = self._conversations.get(conversation_id, customer_id)
        conversation.mark_abandoned(self._clock())
        self._conversations.save(conversation)
        self._discard_photos(conversation)
        return conversation

    def history(self, customer_id: uuid.UUID) -> list[ConversationSummary]:
        """The customer's closed conversations, newest first, for browsing back to one."""
        return self._conversations.list_ended(customer_id, HISTORY_LENGTH)

    def outcome(self) -> TurnOutcome:
        """Where the last streamed turn left the conversation; valid once reply is exhausted."""
        return self._outcome

    def reply(
        self,
        conversation_id: uuid.UUID,
        customer_id: uuid.UUID,
        text: str,
        photo_ids: Sequence[uuid.UUID] = (),
    ) -> Iterator[str]:
        """Stream the assistant's answer, then record the turn and apply any ending.

        Neither turn joins the conversation until the stream is exhausted, so a stream the
        customer walks away from leaves no half-written exchange behind, saved or in memory.

        The turn that reaches MAX_CUSTOMER_TURNS is answered with the handoff and escalated
        without asking the model for another reply.
        """
        conversation = self._conversations.get(conversation_id, customer_id)
        conversation.require_open()
        self._outcome = TurnOutcome(status=ConversationStatus.ACTIVE)
        attached: tuple[Photo, ...] = ()
        if photo_ids:
            assert self._photos is not None, "photo turn without a photo repository"
            attached = tuple(self._photos.get_unbound(conversation_id, photo_ids))
        question = Message(
            id=self._new_id(),
            role=MessageRole.CUSTOMER,
            text=text,
            created_at=self._clock(),
            photos=attached,
        )

        if self._customer_turns(conversation) + 1 >= MAX_CUSTOMER_TURNS:
            yield TURN_CAP_HANDOFF
            self._record_answer(
                conversation,
                question,
                ParsedReply(text=TURN_CAP_HANDOFF, marker=ESCALATE_MARKER, question=None),
            )
            return

        hits = self._document_index.search(text, GROUNDING_HITS) if self._document_index else []
        system = build_system_prompt(hits)

        fragments: list[str] = []
        emitted = 0
        history = [*conversation.messages, question]
        for fragment in self._chat_model.stream(system, history):
            fragments.append(fragment)
            # Offsets index the reply with its leading whitespace already dropped, which is how
            # parse_reply renders the answer below; measuring both from the same text is what
            # lets the final flush resume exactly where the stream held back.
            visible = _visible_prefix("".join(fragments).lstrip())
            if len(visible) > emitted:
                yield visible[emitted:]
                emitted = len(visible)

        parsed = parse_reply("".join(fragments))
        if len(parsed.text) > emitted:
            yield parsed.text[emitted:]
        self._record_answer(conversation, question, parsed)

    @staticmethod
    def _customer_turns(conversation: Conversation) -> int:
        return sum(1 for m in conversation.messages if m.role is MessageRole.CUSTOMER)

    def _record_answer(
        self, conversation: Conversation, question: Message, parsed: ParsedReply
    ) -> None:
        now = self._clock()
        marker = parsed.marker
        conversation.append(question, question.created_at)
        conversation.append(
            Message(
                id=self._new_id(),
                role=MessageRole.ASSISTANT,
                text=parsed.text,
                created_at=now,
            ),
            now,
        )

        if marker == SOLVED_MARKER:
            conversation.mark_solved(now)
            self._outcome = TurnOutcome(status=ConversationStatus.SOLVED)
        elif marker == CLOSED_MARKER:
            conversation.mark_abandoned(now)
            self._outcome = TurnOutcome(status=ConversationStatus.ABANDONED)
        elif marker == ESCALATE_MARKER:
            summary = self._chat_model.summarize(SUMMARY_SYSTEM_PROMPT, conversation.messages)
            description = summary.render()
            opened = self._service_calls.open(
                conversation.customer_id,
                description,
                photos=self._sent_photos(conversation),
                summary=summary,
            )
            conversation.mark_escalated(opened.id, now)
            self._outcome = TurnOutcome(
                status=ConversationStatus.ESCALATED,
                service_call_id=opened.id,
                service_call_description=description,
            )
        else:
            self._outcome = TurnOutcome(
                status=ConversationStatus.ACTIVE, question=parsed.question
            )

        self._conversations.save(conversation)
        if question.photos and self._photos is not None:
            self._photos.bind(question.id, [photo.id for photo in question.photos])
        if marker in (SOLVED_MARKER, CLOSED_MARKER):
            self._discard_photos(conversation)
        elif marker == ESCALATE_MARKER:
            self._discard_unbound(conversation.id)

    @staticmethod
    def _sent_photos(conversation: Conversation) -> tuple[Photo, ...]:
        return tuple(
            photo
            for message in conversation.messages
            if message.role is MessageRole.CUSTOMER
            for photo in message.photos
        )

    def remove_discarded_objects(self) -> None:
        """Delete from the object store what the endings above discarded.

        The caller invokes this only after committing the transaction that recorded the ending —
        the remove-after-commit order the service-call deletion path also follows — so a failed
        commit cannot leave a still-ACTIVE conversation whose images are already gone.
        """
        if self._discarded_keys:
            assert self._photo_store is not None, "discarded keys staged without a photo store"
            self._photo_store.remove(self._discarded_keys)
            self._discarded_keys = []

    def _discard_photos(self, conversation: Conversation) -> None:
        """A conversation that ended without a technician leaves nothing in object storage.

        Metadata rows of sent photos stay so the transcript still names what was attached;
        never-sent uploads lose both their objects and their rows. The objects themselves are
        only staged here; they die in remove_discarded_objects after the ending commits."""
        if self._photos is None or self._photo_store is None:
            return
        unbound = self._photos.list_unbound(conversation.id)
        self._discarded_keys.extend(
            key
            for photo in (*self._sent_photos(conversation), *unbound)
            for key in photo_keys(photo.object_key)
        )
        self._photos.delete_unbound(conversation.id)

    def _discard_unbound(self, conversation_id: uuid.UUID) -> None:
        """Uploads the customer never sent do not follow the escalation to the service call."""
        if self._photos is None or self._photo_store is None:
            return
        unbound = self._photos.list_unbound(conversation_id)
        if unbound:
            self._discarded_keys.extend(
                key for photo in unbound for key in photo_keys(photo.object_key)
            )
            self._photos.delete_unbound(conversation_id)
