"""Outbound port for triage conversation persistence."""
from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable

from fsm.assist.domain.conversation import Conversation, ConversationSummary


@runtime_checkable
class ConversationRepository(Protocol):
    def add(self, conversation: Conversation) -> None:
        """Insert a new conversation and its messages.

        A customer has at most one open conversation, so inserting an open one raises
        ConversationAlreadyOpen when the customer already has one. Inserting an already-ended
        conversation is always accepted.
        """
        ...

    def get(self, conversation_id: uuid.UUID, customer_id: uuid.UUID) -> Conversation:
        """The customer's conversation; raises ConversationNotFound when it is not theirs."""
        ...

    def save(self, conversation: Conversation) -> None:
        """Persist status changes and any messages appended since the last save."""
        ...

    def find_active_for_customer(self, customer_id: uuid.UUID) -> Conversation | None:
        """The customer's one open conversation, if any."""
        ...

    def list_ended(self, customer_id: uuid.UUID, limit: int) -> list[ConversationSummary]:
        """The customer's closed conversations that carry at least one customer turn, newest first.

        Opening the chat inserts a conversation before anything is said, so a customer who never
        typed leaves a message-less row behind; it names no problem and is omitted here.
        """
        ...
