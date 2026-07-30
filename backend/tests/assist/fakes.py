"""In-memory fakes for the assist ports, shared across assist test modules."""
from __future__ import annotations

import uuid
from collections.abc import Iterator, Sequence

from fsm.assist.domain.conversation import (
    OPENING_LINE_CHARS,
    Conversation,
    ConversationSummary,
    Message,
    MessageRole,
    Photo,
)
from fsm.assist.domain.document import KbDocument
from fsm.assist.domain.errors import (
    ConversationAlreadyOpen,
    ConversationNotFound,
    DocumentNotFound,
    PhotoNotFound,
)
from fsm.assist.ports.chat_model import TriageSummary
from fsm.assist.ports.document_index import SearchHit
from fsm.assist.ports.image_processing import InspectedPhoto
from fsm.assist.ports.service_calls import OpenedServiceCall


class FakeKbDocumentRepository:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, KbDocument] = {}
        self.contents: dict[uuid.UUID, bytes] = {}

    def add(self, document: KbDocument, content: bytes) -> None:
        self.rows[document.id] = document
        self.contents[document.id] = content

    def get(self, document_id: uuid.UUID) -> KbDocument:
        try:
            return self.rows[document_id]
        except KeyError:
            raise DocumentNotFound(str(document_id)) from None

    def get_content(self, document_id: uuid.UUID) -> bytes:
        try:
            return self.contents[document_id]
        except KeyError:
            raise DocumentNotFound(str(document_id)) from None

    def find_by_content(self, content: bytes) -> KbDocument | None:
        for document_id, stored in self.contents.items():
            if stored == content:
                return self.rows[document_id]
        return None

    def list_all(self) -> list[KbDocument]:
        return sorted(self.rows.values(), key=lambda d: d.uploaded_at, reverse=True)

    def remove(self, document_id: uuid.UUID) -> None:
        self.get(document_id)
        del self.rows[document_id]
        del self.contents[document_id]

    def update_index_state(
        self, document_id: uuid.UUID, chunk_count: int, embedding_model: str
    ) -> None:
        import dataclasses

        self.rows[document_id] = dataclasses.replace(
            self.get(document_id), chunk_count=chunk_count, embedding_model=embedding_model
        )


class FakeDocumentIndex:
    """Keeps whole texts per document; search returns chunks whose text contains the query."""

    def __init__(self) -> None:
        self.texts: dict[uuid.UUID, tuple[str, str]] = {}  # id -> (filename, text)
        self.reset_calls = 0

    def index_document(
        self,
        document_id: uuid.UUID,
        filename: str,
        text: str,
        on_progress=None,
    ) -> int:
        self.texts[document_id] = (filename, text)
        if on_progress is not None:
            on_progress(1, 1)
        return 1

    def remove_document(self, document_id: uuid.UUID, chunk_count: int) -> None:
        self.texts.pop(document_id, None)

    def search(self, query: str, limit: int) -> list[SearchHit]:
        hits = [
            SearchHit(document_id=doc_id, filename=filename, content=text, score=1.0)
            for doc_id, (filename, text) in self.texts.items()
            if query.lower() in text.lower()
        ]
        return hits[:limit]

    def reset(self) -> None:
        self.texts.clear()
        self.reset_calls += 1


class FakeTextExtractor:
    """Decodes bytes as UTF-8, whatever the claimed type."""

    def extract(self, filename: str, media_type: str, content: bytes, on_progress=None) -> str:
        if on_progress is not None:
            on_progress(1, 1)
        return content.decode("utf-8")


class FakeChatModel:
    """Replays scripted replies; records the prompts it was given.

    Set replies to the assistant turns to emit in order, and summary to what summarize returns.
    """

    def __init__(
        self,
        replies: list[str] | None = None,
        summary: TriageSummary | None = None,
    ) -> None:
        self.replies = list(replies or [])
        self.summary = summary or TriageSummary(
            equipment="Oven",
            problem_category="Not heating",
            symptoms="Stays cold",
            steps_tried="Breaker reset — no change",
            suspected_cause="Heating element",
        )
        self.stream_calls: list[tuple[str, list[Message]]] = []
        self.summarize_calls: list[tuple[str, list[Message]]] = []

    def stream(self, system: str, messages: Sequence[Message]) -> Iterator[str]:
        self.stream_calls.append((system, list(messages)))
        reply = self.replies.pop(0) if self.replies else "Tell me more about the problem."
        for word in reply.split(" "):
            yield word + " "

    def summarize(self, system: str, messages: Sequence[Message]) -> TriageSummary:
        self.summarize_calls.append((system, list(messages)))
        return self.summary


class FakeConversationRepository:
    """Mirrors the store's one-ACTIVE-conversation-per-customer rejection on add."""

    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Conversation] = {}

    def add(self, conversation: Conversation) -> None:
        """Rejects a second open conversation, exactly as the partial unique index does.

        The index covers only ACTIVE rows, so an already-ended conversation can still be inserted
        alongside an open one.
        """
        if conversation.is_open():
            if self.find_active_for_customer(conversation.customer_id) is not None:
                raise ConversationAlreadyOpen(str(conversation.customer_id))
        self.rows[conversation.id] = conversation

    def get(self, conversation_id: uuid.UUID, customer_id: uuid.UUID) -> Conversation:
        convo = self.rows.get(conversation_id)
        if convo is None or convo.customer_id != customer_id:
            raise ConversationNotFound(str(conversation_id))
        return convo

    def save(self, conversation: Conversation) -> None:
        self.rows[conversation.id] = conversation

    def find_active_for_customer(self, customer_id: uuid.UUID) -> Conversation | None:
        for convo in self.rows.values():
            if convo.customer_id == customer_id and convo.is_open():
                return convo
        return None

    def list_ended(self, customer_id: uuid.UUID, limit: int) -> list[ConversationSummary]:
        ended = [
            ConversationSummary(
                id=convo.id,
                status=convo.status,
                updated_at=convo.updated_at,
                opening_line=openings[0].text[:OPENING_LINE_CHARS],
            )
            for convo in self.rows.values()
            if convo.customer_id == customer_id
            and not convo.is_open()
            and (openings := [m for m in convo.messages if m.role is MessageRole.CUSTOMER])
        ]
        return sorted(ended, key=lambda s: s.updated_at, reverse=True)[:limit]


class FakeServiceCallOpener:
    def __init__(self) -> None:
        self.opened: list[OpenedServiceCall] = []
        self.opened_photos: list[list[Photo]] = []

    def open(
        self, customer_id: uuid.UUID, description: str, photos: Sequence[Photo] = ()
    ) -> OpenedServiceCall:
        call = OpenedServiceCall(id=uuid.uuid4(), description=description)
        self.opened.append(call)
        self.opened_photos.append(list(photos))
        return call


class FakePhotoStore:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.removed: list[str] = []

    def put(self, key: str, content: bytes, media_type: str) -> None:
        self.objects[key] = (content, media_type)

    def get(self, key: str) -> bytes:
        return self.objects[key][0]

    def remove(self, keys: Sequence[str]) -> None:
        for key in keys:
            del self.objects[key]
            self.removed.append(key)


class FakePreviewMaker:
    def prepare(self, content: bytes) -> InspectedPhoto:
        return InspectedPhoto(media_type="image/jpeg", preview_jpeg=b"preview:" + content)


class FakePhotoRepository:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, tuple[uuid.UUID, Photo]] = {}  # photo id -> (conversation, photo)
        self.bound: dict[uuid.UUID, uuid.UUID] = {}  # photo id -> message id

    def add(self, conversation_id: uuid.UUID, photo: Photo) -> None:
        self.rows[photo.id] = (conversation_id, photo)

    def count_for_conversation(self, conversation_id: uuid.UUID) -> int:
        return sum(1 for cid, _ in self.rows.values() if cid == conversation_id)

    def get_unbound(
        self, conversation_id: uuid.UUID, photo_ids: Sequence[uuid.UUID]
    ) -> list[Photo]:
        photos = []
        for photo_id in photo_ids:
            row = self.rows.get(photo_id)
            if row is None or row[0] != conversation_id or photo_id in self.bound:
                raise PhotoNotFound(str(photo_id))
            photos.append(row[1])
        return photos

    def bind(self, message_id: uuid.UUID, photo_ids: Sequence[uuid.UUID]) -> None:
        for photo_id in photo_ids:
            self.bound[photo_id] = message_id

    def list_unbound(self, conversation_id: uuid.UUID) -> list[Photo]:
        return [
            photo
            for photo_id, (cid, photo) in self.rows.items()
            if cid == conversation_id and photo_id not in self.bound
        ]

    def delete_unbound(self, conversation_id: uuid.UUID) -> None:
        for photo_id in [
            pid
            for pid, (cid, _) in self.rows.items()
            if cid == conversation_id and pid not in self.bound
        ]:
            del self.rows[photo_id]

    def get(self, conversation_id: uuid.UUID, photo_id: uuid.UUID) -> Photo:
        row = self.rows.get(photo_id)
        if row is None or row[0] != conversation_id:
            raise PhotoNotFound(str(photo_id))
        return row[1]

    def delete(self, photo_id: uuid.UUID) -> None:
        del self.rows[photo_id]
        self.bound.pop(photo_id, None)
