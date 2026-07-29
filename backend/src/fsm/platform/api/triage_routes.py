"""Customer triage chat: open a conversation, stream a turn, escalate it, or close it."""
from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, StringConstraints

from fsm.assist.application.triage import TriageService
from fsm.assist.domain.conversation import Conversation
from fsm.identity.domain.role import Role
from fsm.platform.api.auth_deps import SessionUser, require_role, require_user

router = APIRouter(prefix="/api/assist")


MAX_MESSAGE_CHARS = 4000


class SendMessageRequest(BaseModel):
    """One customer turn, bounded so a single authenticated caller cannot drive unbounded text
    into a metered model API and the conversation store; the endpoint is not rate limited."""

    text: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_MESSAGE_CHARS),
    ]


def _session_factory(request: Request):
    from fsm.platform.app import _get_session_factory

    return _get_session_factory(request.app)


def _chat_model(request: Request):
    model = getattr(request.app.state, "assist_chat_model", None)
    if model is None:
        raise HTTPException(status_code=503, detail="Triage assistant not configured")
    return model


def _service(request: Request, session) -> TriageService:
    """A service per request: outcome() is per-turn state that must not be shared between callers."""
    from fsm.assist.adapters.conversation_repository import SqlAlchemyConversationRepository
    from fsm.platform.service_call_bridge import build_service_call_opener

    return TriageService(
        conversations=SqlAlchemyConversationRepository(session),
        chat_model=_chat_model(request),
        service_calls=build_service_call_opener(session),
    )


def _conversation_json(conversation: Conversation) -> dict:
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
            }
            for m in conversation.messages
        ],
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
    with _session_factory(request)() as session:
        conversation = _service(request, session).start(user.id)
        session.commit()
        return _conversation_json(conversation)


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
    with _session_factory(request)() as session:
        return _conversation_json(_service(request, session).get(conversation_id, user.id))


@router.post("/conversations/{conversation_id}/end")
def end_conversation(
    conversation_id: uuid.UUID,
    request: Request,
    user: SessionUser = Depends(require_role(Role.CUSTOMER)),
) -> dict:
    """Close the conversation at the customer's request, opening no service call."""
    with _session_factory(request)() as session:
        conversation = _service(request, session).end(conversation_id, user.id)
        session.commit()
        return _conversation_json(conversation)


@router.post("/conversations/{conversation_id}/messages")
def send_message(
    conversation_id: uuid.UUID,
    body: SendMessageRequest,
    request: Request,
    user: SessionUser = Depends(require_role(Role.CUSTOMER)),
) -> StreamingResponse:
    """Stream the assistant's reply, committing the turn once the model has finished.

    The conversation is resolved here rather than left to the generator: once StreamingResponse
    is returned the 200 headers are already on the wire, so an unknown or closed conversation
    would arrive as a broken stream instead of the 404 or 409 it is.

    The generator is synchronous so FastAPI runs it in the threadpool: the model call and the
    commit both block, and neither may stall the event loop.
    """
    with _session_factory(request)() as session:
        _service(request, session).get(conversation_id, user.id).require_open()

    def turn() -> Iterator[str]:
        with _session_factory(request)() as session:
            service = _service(request, session)
            for fragment in service.reply(conversation_id, user.id, body.text):
                if fragment:
                    yield _sse("token", {"text": fragment})
            session.commit()
            outcome = service.outcome()
            yield _sse(
                "done",
                {
                    "status": outcome.status.value,
                    "service_call": (
                        None
                        if outcome.service_call_id is None
                        else {
                            "id": str(outcome.service_call_id),
                            "description": outcome.service_call_description,
                        }
                    ),
                },
            )

    return StreamingResponse(turn(), media_type="text/event-stream")
