"""Customer triage chat: open a conversation, stream a turn, escalate it, or close it."""
from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, StringConstraints, model_validator

from fsm.assist.adapters.image_processing import PillowPreviewMaker
from fsm.assist.application.photos import PhotoService
from fsm.assist.application.triage import TriageService
from fsm.assist.domain.conversation import MAX_PHOTOS_PER_CONVERSATION, Conversation, Photo
from fsm.assist.ports.photo_store import preview_key
from fsm.identity.domain.role import Role
from fsm.platform.api.auth_deps import SessionUser, require_role, require_user

router = APIRouter(prefix="/api/assist")


MAX_MESSAGE_CHARS = 4000

MAX_PHOTO_MB = 5
MAX_PHOTO_BYTES = MAX_PHOTO_MB * 1024 * 1024

_preview_maker = PillowPreviewMaker()


class SendMessageRequest(BaseModel):
    """One customer turn, bounded so a single authenticated caller cannot drive unbounded text
    into a metered model API and the conversation store; the endpoint is not rate limited.

    A turn needs text, photos, or both — photos alone are a valid turn the assistant reads on
    their own — so only the combination of blank text and no photos is rejected.
    """

    text: Annotated[
        str,
        StringConstraints(strip_whitespace=True, max_length=MAX_MESSAGE_CHARS),
    ] = ""
    photo_ids: list[uuid.UUID] = Field(
        default_factory=list, max_length=MAX_PHOTOS_PER_CONVERSATION
    )

    @model_validator(mode="after")
    def _text_or_photos(self) -> "SendMessageRequest":
        if not self.text and not self.photo_ids:
            raise ValueError("A message needs text or at least one photo.")
        return self


def _session_factory(request: Request):
    from fsm.platform.app import _get_session_factory

    return _get_session_factory(request.app)


def _chat_model(request: Request):
    model = getattr(request.app.state, "assist_chat_model", None)
    if model is None:
        raise HTTPException(status_code=503, detail="Triage assistant not configured")
    return model


def _photo_store(request: Request):
    store = getattr(request.app.state, "photo_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Triage assistant not configured")
    return store


def _service(request: Request, session) -> TriageService:
    """A service per request: outcome() is per-turn state that must not be shared between callers."""
    from fsm.assist.adapters.conversation_repository import SqlAlchemyConversationRepository
    from fsm.assist.adapters.photo_repository import SqlAlchemyPhotoRepository
    from fsm.platform.service_call_bridge import build_service_call_opener

    return TriageService(
        conversations=SqlAlchemyConversationRepository(session),
        chat_model=_chat_model(request),
        service_calls=build_service_call_opener(session),
        document_index=getattr(request.app.state, "kb_index", None),
        photos=SqlAlchemyPhotoRepository(session),
        photo_store=getattr(request.app.state, "photo_store", None),
    )


def _photo_service(request: Request, session) -> PhotoService:
    from fsm.assist.adapters.conversation_repository import SqlAlchemyConversationRepository
    from fsm.assist.adapters.photo_repository import SqlAlchemyPhotoRepository

    return PhotoService(
        conversations=SqlAlchemyConversationRepository(session),
        photos=SqlAlchemyPhotoRepository(session),
        photo_store=_photo_store(request),
        preview_maker=_preview_maker,
    )


def _photo_json(photo: Photo) -> dict:
    return {"id": str(photo.id), "filename": photo.filename, "size_bytes": photo.size_bytes}


def _conversation_json(conversation: Conversation, pending_photos: list[Photo]) -> dict:
    return {
        "id": str(conversation.id),
        "status": conversation.status.value,
        "service_call_id": (
            None if conversation.service_call_id is None else str(conversation.service_call_id)
        ),
        "messages": [
            {
                "id": str(m.id),
                "role": m.role.value,
                "text": m.text,
                "created_at": m.created_at.isoformat(),
                "photos": [_photo_json(p) for p in m.photos],
            }
            for m in conversation.messages
        ],
        "pending_photos": [_photo_json(p) for p in pending_photos],
    }


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


@router.get("/status")
def assist_status(request: Request, user: SessionUser = Depends(require_user)) -> dict:
    """Whether the triage chat is configured; the customer page picks chat or form from this."""
    return {"enabled": getattr(request.app.state, "assist_chat_model", None) is not None}


@router.post("/conversations")
def start_conversation(
    request: Request, user: SessionUser = Depends(require_role(Role.CUSTOMER))
) -> dict:
    from fsm.assist.adapters.photo_repository import SqlAlchemyPhotoRepository

    with _session_factory(request)() as session:
        service = _service(request, session)
        conversation = service.start(user.id)
        session.commit()
        service.remove_discarded_objects()
        pending_photos = SqlAlchemyPhotoRepository(session).list_unbound(conversation.id)
        return _conversation_json(conversation, pending_photos)


@router.get("/conversations")
def list_conversations(
    request: Request, user: SessionUser = Depends(require_role(Role.CUSTOMER))
) -> dict:
    """The customer's closed conversations as one-line summaries; transcripts are fetched by id."""
    with _session_factory(request)() as session:
        return {
            "conversations": [
                {
                    "id": str(summary.id),
                    "status": summary.status.value,
                    "updated_at": summary.updated_at.isoformat(),
                    "opening_line": summary.opening_line,
                }
                for summary in _service(request, session).history(user.id)
            ]
        }


@router.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: uuid.UUID,
    request: Request,
    user: SessionUser = Depends(require_role(Role.CUSTOMER)),
) -> dict:
    from fsm.assist.adapters.photo_repository import SqlAlchemyPhotoRepository

    with _session_factory(request)() as session:
        conversation = _service(request, session).get(conversation_id, user.id)
        pending_photos = SqlAlchemyPhotoRepository(session).list_unbound(conversation_id)
        return _conversation_json(conversation, pending_photos)


@router.post("/conversations/{conversation_id}/end")
def end_conversation(
    conversation_id: uuid.UUID,
    request: Request,
    user: SessionUser = Depends(require_role(Role.CUSTOMER)),
) -> dict:
    """Close the conversation at the customer's request, opening no service call.

    Ending discards every photo the customer had attached but not sent, so the closed
    conversation carries none.
    """
    with _session_factory(request)() as session:
        service = _service(request, session)
        conversation = service.end(conversation_id, user.id)
        session.commit()
        service.remove_discarded_objects()
        return _conversation_json(conversation, [])


@router.post("/conversations/{conversation_id}/photos", status_code=201)
async def upload_photo(
    conversation_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    user: SessionUser = Depends(require_role(Role.CUSTOMER)),
) -> dict:
    content = await file.read()
    if len(content) > MAX_PHOTO_BYTES:
        raise HTTPException(
            status_code=413, detail=f"Photo exceeds the {MAX_PHOTO_MB} MB limit"
        )
    filename = file.filename or "photo"

    def _attach() -> dict:
        with _session_factory(request)() as session:
            photo = _photo_service(request, session).attach(
                conversation_id, user.id, filename, content
            )
            session.commit()
            return {
                "id": str(photo.id),
                "filename": photo.filename,
                "media_type": photo.media_type,
                "size_bytes": photo.size_bytes,
            }

    return await run_in_threadpool(_attach)


@router.get("/conversations/{conversation_id}/photos/{photo_id}/preview")
def photo_preview(
    conversation_id: uuid.UUID,
    photo_id: uuid.UUID,
    request: Request,
    user: SessionUser = Depends(require_role(Role.CUSTOMER)),
) -> Response:
    """The downscaled preview of one of the caller's own photos, bound or still pending."""
    from fsm.assist.adapters.photo_repository import SqlAlchemyPhotoRepository

    with _session_factory(request)() as session:
        _service(request, session).get(conversation_id, user.id)
        photo = SqlAlchemyPhotoRepository(session).get(conversation_id, photo_id)
        content = _photo_store(request).get(preview_key(photo.object_key))
    return Response(content=content, media_type="image/jpeg")


@router.delete("/conversations/{conversation_id}/photos/{photo_id}", status_code=204)
def delete_photo(
    conversation_id: uuid.UUID,
    photo_id: uuid.UUID,
    request: Request,
    user: SessionUser = Depends(require_role(Role.CUSTOMER)),
) -> Response:
    """Detaches a pending photo the customer changed their mind about before it was sent."""
    with _session_factory(request)() as session:
        _photo_service(request, session).detach(conversation_id, user.id, photo_id)
        session.commit()
    return Response(status_code=204)


@router.post("/conversations/{conversation_id}/messages")
def send_message(
    conversation_id: uuid.UUID,
    body: SendMessageRequest,
    request: Request,
    user: SessionUser = Depends(require_role(Role.CUSTOMER)),
) -> StreamingResponse:
    """Stream the assistant's reply, committing the turn once the model has finished.

    The conversation and any attached photo ids are resolved here rather than left to the
    generator: once StreamingResponse is returned the 200 headers are already on the wire, so an
    unknown or closed conversation, or a photo id that does not resolve, would arrive as a broken
    stream instead of the 404 or 409 it is.

    The generator is synchronous so FastAPI runs it in the threadpool: the model call and the
    commit both block, and neither may stall the event loop.
    """
    from fsm.assist.adapters.photo_repository import SqlAlchemyPhotoRepository

    with _session_factory(request)() as session:
        _service(request, session).get(conversation_id, user.id).require_open()
        if body.photo_ids:
            SqlAlchemyPhotoRepository(session).get_unbound(conversation_id, body.photo_ids)

    def turn() -> Iterator[str]:
        with _session_factory(request)() as session:
            service = _service(request, session)
            for fragment in service.reply(conversation_id, user.id, body.text, body.photo_ids):
                if fragment:
                    yield _sse("token", {"text": fragment})
            session.commit()
            service.remove_discarded_objects()
            outcome = service.outcome()
            yield _sse(
                "done",
                {
                    "status": outcome.status.value,
                    "question": (
                        None
                        if outcome.question is None
                        else {"start": outcome.question.start, "end": outcome.question.end}
                    ),
                    "service_call": (
                        None
                        if outcome.service_call_id is None
                        else {
                            "id": str(outcome.service_call_id),
                            "description": outcome.service_call_description,
                        }
                    ),
                    "sources": [
                        {
                            "id": str(source.id),
                            "filename": source.filename,
                            "page": source.page,
                        }
                        for source in outcome.sources
                    ],
                },
            )

    return StreamingResponse(turn(), media_type="text/event-stream")
