"""Persistence port for photo metadata. A photo starts unbound; sending the turn binds it to
that customer message, which is what carries it to the model and, on escalation, to the call."""
from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from fsm.assist.domain.conversation import Photo


@runtime_checkable
class PhotoRepository(Protocol):
    def add(self, conversation_id: uuid.UUID, photo: Photo) -> None: ...

    def count_for_conversation(self, conversation_id: uuid.UUID) -> int: ...

    def get_unbound(
        self, conversation_id: uuid.UUID, photo_ids: Sequence[uuid.UUID]
    ) -> list[Photo]:
        """The requested photos, in request order. Raises PhotoNotFound if any id is missing,
        already bound, or belongs to another conversation."""
        ...

    def bind(self, message_id: uuid.UUID, photo_ids: Sequence[uuid.UUID]) -> None: ...

    def list_unbound(self, conversation_id: uuid.UUID) -> list[Photo]: ...

    def delete_unbound(self, conversation_id: uuid.UUID) -> None: ...

    def get(self, conversation_id: uuid.UUID, photo_id: uuid.UUID) -> Photo:
        """The photo regardless of bind state. Raises PhotoNotFound if absent or belonging to
        another conversation."""
        ...

    def delete(self, photo_id: uuid.UUID) -> None:
        """Delete one photo row by id, whatever conversation it belongs to.

        Ownership and bind state are the caller's to check; this removes what it is given.
        """
        ...
