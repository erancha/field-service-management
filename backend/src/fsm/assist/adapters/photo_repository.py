"""Session-scoped SQLAlchemy adapter for photo metadata; caller owns the transaction."""
from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from fsm.assist.adapters.orm import AssistPhotoRow
from fsm.assist.domain.conversation import Photo
from fsm.assist.domain.errors import PhotoNotFound


def _to_photo(row: AssistPhotoRow) -> Photo:
    return Photo(
        id=row.id,
        filename=row.filename,
        media_type=row.media_type,
        size_bytes=row.size_bytes,
        object_key=row.object_key,
        created_at=row.created_at,
    )


class SqlAlchemyPhotoRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, conversation_id: uuid.UUID, photo: Photo) -> None:
        self._session.add(
            AssistPhotoRow(
                id=photo.id,
                conversation_id=conversation_id,
                message_id=None,
                filename=photo.filename,
                media_type=photo.media_type,
                size_bytes=photo.size_bytes,
                object_key=photo.object_key,
                created_at=photo.created_at,
            )
        )
        self._session.flush()

    def count_for_conversation(self, conversation_id: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(AssistPhotoRow)
            .where(AssistPhotoRow.conversation_id == conversation_id)
        )
        return self._session.execute(stmt).scalar_one()

    def get_unbound(
        self, conversation_id: uuid.UUID, photo_ids: Sequence[uuid.UUID]
    ) -> list[Photo]:
        stmt = select(AssistPhotoRow).where(
            AssistPhotoRow.id.in_(photo_ids),
            AssistPhotoRow.conversation_id == conversation_id,
            AssistPhotoRow.message_id.is_(None),
        )
        by_id = {row.id: _to_photo(row) for row in self._session.execute(stmt).scalars()}
        photos = []
        for photo_id in photo_ids:
            if photo_id not in by_id:
                raise PhotoNotFound(str(photo_id))
            photos.append(by_id[photo_id])
        return photos

    def bind(self, message_id: uuid.UUID, photo_ids: Sequence[uuid.UUID]) -> None:
        self._session.execute(
            update(AssistPhotoRow)
            .where(AssistPhotoRow.id.in_(photo_ids))
            .values(message_id=message_id)
        )

    def list_unbound(self, conversation_id: uuid.UUID) -> list[Photo]:
        stmt = select(AssistPhotoRow).where(
            AssistPhotoRow.conversation_id == conversation_id,
            AssistPhotoRow.message_id.is_(None),
        )
        return [_to_photo(row) for row in self._session.execute(stmt).scalars()]

    def delete_unbound(self, conversation_id: uuid.UUID) -> None:
        self._session.execute(
            delete(AssistPhotoRow).where(
                AssistPhotoRow.conversation_id == conversation_id,
                AssistPhotoRow.message_id.is_(None),
            )
        )

    def get(self, conversation_id: uuid.UUID, photo_id: uuid.UUID) -> Photo:
        stmt = select(AssistPhotoRow).where(
            AssistPhotoRow.id == photo_id,
            AssistPhotoRow.conversation_id == conversation_id,
        )
        row = self._session.execute(stmt).scalar_one_or_none()
        if row is None:
            raise PhotoNotFound(str(photo_id))
        return _to_photo(row)

    def delete(self, photo_id: uuid.UUID) -> None:
        self._session.execute(delete(AssistPhotoRow).where(AssistPhotoRow.id == photo_id))
