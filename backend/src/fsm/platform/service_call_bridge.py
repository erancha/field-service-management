"""Implements assist's ServiceCallOpener over the scheduling context.

Assist may not import scheduling; the composition root is the only place that sees both, so an
escalating triage conversation opens its service call through here.
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy.orm import Session

from fsm.assist.domain.conversation import Photo
from fsm.assist.ports.photo_store import PhotoStore, photo_keys
from fsm.assist.ports.service_calls import OpenedServiceCall, ServiceCallOpener
from fsm.scheduling.adapters.repositories import (
    SqlAlchemyServiceCallAttachmentRepository,
    SqlAlchemyServiceCallRepository,
)
from fsm.scheduling.application.service_call_service import ServiceCallService
from fsm.scheduling.domain.attachment import ServiceCallAttachment


class SchedulingServiceCallOpener:
    """Caller owns the transaction; the service call is staged on the given session."""

    def __init__(self, session: Session) -> None:
        self._service = ServiceCallService(
            service_calls=SqlAlchemyServiceCallRepository(session)
        )
        self._attachments = SqlAlchemyServiceCallAttachmentRepository(session)

    def open(
        self, customer_id: uuid.UUID, description: str, photos: Sequence[Photo] = ()
    ) -> OpenedServiceCall:
        service_call = self._service.open_service_call(customer_id, description)
        self._attachments.add_all(
            [
                ServiceCallAttachment(
                    id=photo.id,
                    service_call_id=service_call.id,
                    filename=photo.filename,
                    media_type=photo.media_type,
                    size_bytes=photo.size_bytes,
                    object_key=photo.object_key,
                    created_at=photo.created_at,
                )
                for photo in photos
            ]
        )
        return OpenedServiceCall(id=service_call.id, description=service_call.description)


def build_service_call_opener(session: Session) -> ServiceCallOpener:
    return SchedulingServiceCallOpener(session)


def delete_service_call(
    session: Session, photo_store: PhotoStore, service_call_id: uuid.UUID
) -> None:
    """Remove a service call together with its photos.

    Attachment rows die with the call row via the FK cascade; the objects are removed after the
    delete commits, since a failed commit must not have already destroyed them. No route exposes
    this yet — it is the deletion path any future admin surface must call, and the reason manual
    row deletes are not enough: the database cannot reach MinIO.
    """
    attachments = SqlAlchemyServiceCallAttachmentRepository(session)
    keys = [
        key
        for attachment in attachments.list_for_service_call(service_call_id)
        for key in photo_keys(attachment.object_key)
    ]
    SqlAlchemyServiceCallRepository(session).remove(service_call_id)
    session.commit()
    if keys:
        photo_store.remove(keys)
