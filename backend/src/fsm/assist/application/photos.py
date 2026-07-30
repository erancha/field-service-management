"""Attaches customer photos to an open conversation ahead of the turn that will carry them."""
from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timezone

from fsm.assist.domain.conversation import MAX_PHOTOS_PER_CONVERSATION, Photo
from fsm.assist.domain.errors import PhotoLimitReached
from fsm.assist.ports.conversation_repository import ConversationRepository
from fsm.assist.ports.image_processing import PreviewMaker
from fsm.assist.ports.photo_repository import PhotoRepository
from fsm.assist.ports.photo_store import (
    PhotoStore,
    object_prefix,
    original_key,
    photo_keys,
    preview_key,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PhotoService:
    """Validates, downscales, and stores one uploaded photo; the turn endpoint binds it later."""

    def __init__(
        self,
        conversations: ConversationRepository,
        photos: PhotoRepository,
        photo_store: PhotoStore,
        preview_maker: PreviewMaker,
        *,
        clock: Callable[[], datetime] = _utc_now,
        id_factory: Callable[[], uuid.UUID] = uuid.uuid4,
    ) -> None:
        self._conversations = conversations
        self._photos = photos
        self._photo_store = photo_store
        self._preview_maker = preview_maker
        self._clock = clock
        self._new_id = id_factory

    def attach(
        self, conversation_id: uuid.UUID, customer_id: uuid.UUID, filename: str, content: bytes
    ) -> Photo:
        self._conversations.get(conversation_id, customer_id).require_open()
        if self._photos.count_for_conversation(conversation_id) >= MAX_PHOTOS_PER_CONVERSATION:
            raise PhotoLimitReached(
                f"A conversation can carry at most {MAX_PHOTOS_PER_CONVERSATION} photos"
            )

        inspected = self._preview_maker.prepare(content)
        photo_id = self._new_id()
        photo = Photo(
            id=photo_id,
            filename=filename,
            media_type=inspected.media_type,
            size_bytes=len(content),
            object_key=object_prefix(photo_id),
            created_at=self._clock(),
        )
        self._photo_store.put(original_key(photo.object_key), content, inspected.media_type)
        self._photo_store.put(preview_key(photo.object_key), inspected.preview_jpeg, "image/jpeg")
        self._photos.add(conversation_id, photo)
        return photo

    def detach(self, conversation_id: uuid.UUID, customer_id: uuid.UUID, photo_id: uuid.UUID) -> None:
        """Remove a pending photo the customer changed their mind about; sent photos are part of
        the transcript and cannot be detached."""
        self._conversations.get(conversation_id, customer_id).require_open()
        (photo,) = self._photos.get_unbound(conversation_id, [photo_id])
        self._photo_store.remove(photo_keys(photo.object_key))
        self._photos.delete(photo.id)
