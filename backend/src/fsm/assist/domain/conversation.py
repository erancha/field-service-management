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

    equipment is what the assistant has determined the exchange is about, in make-model-type form,
    and None until it can tell. It holds only the current identity, not the corrections that led to
    it.

    triage_declined records the customer's standing request to skip troubleshooting and go straight
    to a technician. It lives here rather than in the transcript alone so every turn — including
    one retried after a failure — rebuilds the same regime.
    """

    id: uuid.UUID
    customer_id: uuid.UUID
    status: ConversationStatus
    created_at: datetime
    updated_at: datetime
    messages: list[Message] = field(default_factory=list)
    service_call_id: uuid.UUID | None = None
    equipment: str | None = None
    triage_declined: bool = False

    def is_open(self) -> bool:
        return self.status is ConversationStatus.ACTIVE

    def is_expired(self, now: datetime) -> bool:
        """An open conversation the customer walked away from; closed ones never expire."""
        return self.is_open() and now - self.updated_at > CONVERSATION_TTL

    def append(self, message: Message, now: datetime) -> None:
        self.require_open()
        self.messages.append(message)
        self.updated_at = now

    def identify_equipment(self, identity: str) -> None:
        """Record what the equipment has turned out to be, replacing any earlier identification.

        Later beats earlier because identification improves with the conversation: a guess from a
        blurred photo gives way to the model number off the rating plate.
        """
        self.require_open()
        self.equipment = identity

    def decline_triage(self) -> None:
        """Record the customer's request to skip troubleshooting and go straight to a technician."""
        self.require_open()
        self.triage_declined = True

    def resume_triage(self) -> None:
        """Record that the customer wants to try fixes after all, reopening normal triage."""
        self.require_open()
        self.triage_declined = False

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
