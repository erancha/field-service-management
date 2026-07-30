"""HTTP status mapping for assist domain errors, shared by every assist route module."""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from fsm.assist.domain.errors import (
    AssistError,
    ConversationAlreadyOpen,
    ConversationClosed,
    ConversationNotFound,
    DocumentNotFound,
    DuplicateDocument,
    EmptyDocumentText,
    IndexModelMismatch,
    PhotoLimitReached,
    PhotoNotFound,
    UnsupportedDocumentType,
    UnsupportedPhoto,
)


def handle_assist_error(request: Request, exc: AssistError) -> JSONResponse:
    """Maps assist domain errors to HTTP statuses.

    The mapping is exhaustive on purpose: a new AssistError subtype raises KeyError (a 500)
    until it is given a status here, rather than silently degrading to a generic response.
    """
    status = {
        UnsupportedDocumentType: 415,
        EmptyDocumentText: 422,
        DocumentNotFound: 404,
        DuplicateDocument: 409,
        IndexModelMismatch: 409,
        ConversationNotFound: 404,
        ConversationClosed: 409,
        ConversationAlreadyOpen: 409,
        UnsupportedPhoto: 415,
        PhotoLimitReached: 409,
        PhotoNotFound: 404,
    }[type(exc)]
    return JSONResponse({"detail": str(exc) or type(exc).__name__}, status_code=status)
