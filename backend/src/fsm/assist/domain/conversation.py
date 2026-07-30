"""Triage conversation between a customer and the assistant."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from fsm.assist.domain.errors import ConversationClosed

CONVERSATION_TTL = timedelta(hours=24)
MAX_PHOTOS_PER_CONVERSATION = 5
"""Photos one conversation may carry, bounding storage and per-turn model cost."""


class ConversationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SOLVED = "SOLVED"
    ESCALATED = "ESCALATED"
    ABANDONED = "ABANDONED"


class MessageRole(str, Enum):
    CUSTOMER = "CUSTOMER"
    ASSISTANT = "ASSISTANT"


@dataclass(frozen=True)
class Photo:
    """A customer-attached photo. The bytes live in object storage under object_key (a per-photo
    prefix holding the full-resolution original and the model-sized preview); this metadata is
    what the rest of the system passes around."""

    id: uuid.UUID
    filename: str
    media_type: str
    size_bytes: int
    object_key: str
    created_at: datetime


@dataclass(frozen=True)
class Message:
    """One turn of the conversation, in the order it was said."""

    id: uuid.UUID
    role: MessageRole
    text: str
    created_at: datetime
    photos: tuple[Photo, ...] = ()


@dataclass
class Conversation:
    """A triage exchange with exactly one ending: solved, escalated, or abandoned.

    service_call_id is set only on escalation and refers to a scheduling service call by id;
    cross-context references stay by-id.
    """

    id: uuid.UUID
    customer_id: uuid.UUID
    status: ConversationStatus
    created_at: datetime
    updated_at: datetime
    messages: list[Message] = field(default_factory=list)
    service_call_id: uuid.UUID | None = None

    def is_open(self) -> bool:
        return self.status is ConversationStatus.ACTIVE

    def is_expired(self, now: datetime) -> bool:
        """An open conversation the customer walked away from; closed ones never expire."""
        return self.is_open() and now - self.updated_at > CONVERSATION_TTL

    def append(self, message: Message, now: datetime) -> None:
        self.require_open()
        self.messages.append(message)
        self.updated_at = now

    def mark_solved(self, now: datetime) -> None:
        self._close(ConversationStatus.SOLVED, now)

    def mark_escalated(self, service_call_id: uuid.UUID, now: datetime) -> None:
        self._close(ConversationStatus.ESCALATED, now)
        self.service_call_id = service_call_id

    def mark_abandoned(self, now: datetime) -> None:
        self._close(ConversationStatus.ABANDONED, now)

    def _close(self, status: ConversationStatus, now: datetime) -> None:
        self.require_open()
        self.status = status
        self.updated_at = now

    def require_open(self) -> None:
        """The precondition behind every mutation; callers check it before doing work."""
        if not self.is_open():
            raise ConversationClosed(str(self.id))


@dataclass(frozen=True)
class ConversationSummary:
    """One row of a customer's conversation history: enough to recognise an exchange, not read it.

    opening_line is the customer's first message, shortened to OPENING_LINE_CHARS by the store so
    a list of long openers cannot outweigh the transcript the customer actually asks for. Reading
    an exchange means fetching the conversation itself.
    """

    id: uuid.UUID
    status: ConversationStatus
    updated_at: datetime
    opening_line: str


OPENING_LINE_CHARS = 160
