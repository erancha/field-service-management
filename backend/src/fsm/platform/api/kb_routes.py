"""Back-office knowledge-base management: upload, list, delete, search, re-index (ADMIN only)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from fsm.assist.application.knowledge_base import KnowledgeBaseService
from fsm.assist.domain.document import KbDocument
from fsm.identity.domain.role import Role
from fsm.platform.api.auth_deps import SessionUser, require_role
from fsm.platform.assist_factory import build_text_extractor
from fsm.platform.config import Settings

router = APIRouter(prefix="/api/kb")

MAX_UPLOAD_BYTES = 10 * 1024 * 1024

_extractor = build_text_extractor()


class SearchRequest(BaseModel):
    query: str


def _session_factory(request: Request):
    from fsm.platform.app import _get_session_factory

    return _get_session_factory(request.app)


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _index(request: Request):
    index = getattr(request.app.state, "kb_index", None)
    if index is None:
        raise HTTPException(status_code=503, detail="Knowledge base not configured")
    return index


def _embedding_model(request: Request) -> str:
    model = _settings(request).assist_embeddings
    assert model is not None  # kb_index exists only when an embeddings model is configured
    return model


def _service(request: Request, session) -> KnowledgeBaseService:
    from fsm.assist.adapters.document_repository import SqlAlchemyKbDocumentRepository

    return KnowledgeBaseService(
        documents=SqlAlchemyKbDocumentRepository(session),
        index=_index(request),
        extractor=_extractor,
        embedding_model=_embedding_model(request),
    )


def _doc_json(doc: KbDocument) -> dict:
    return {
        "id": str(doc.id),
        "filename": doc.filename,
        "size_bytes": doc.size_bytes,
        "uploaded_at": doc.uploaded_at.isoformat(),
        "chunk_count": doc.chunk_count,
    }


@router.get("/status")
def kb_status(request: Request, admin: SessionUser = Depends(require_role(Role.ADMIN))) -> dict:
    if getattr(request.app.state, "kb_index", None) is None:
        return {"enabled": False, "embedding_model": None, "needs_reindex": False}
    with _session_factory(request)() as session:
        svc = _service(request, session)
        return {
            "enabled": True,
            "embedding_model": _embedding_model(request),
            "needs_reindex": svc.needs_reindex(),
        }


@router.get("/documents")
def list_documents(
    request: Request, admin: SessionUser = Depends(require_role(Role.ADMIN))
) -> list[dict]:
    with _session_factory(request)() as session:
        return [_doc_json(d) for d in _service(request, session).list_documents()]


@router.post("/documents", status_code=201)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    admin: SessionUser = Depends(require_role(Role.ADMIN)),
) -> dict:
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Document exceeds the 10 MB limit")

    # Extraction, embedding, and the commit are synchronous (CPU and blocking HTTP/DB I/O);
    # they run in the threadpool so the event loop stays responsive during the upload.
    def _ingest() -> dict:
        with _session_factory(request)() as session:
            doc = _service(request, session).upload(
                filename=file.filename or "document",
                media_type=file.content_type or "application/octet-stream",
                content=content,
                uploaded_by=admin.id,
            )
            session.commit()
            return _doc_json(doc)

    return await run_in_threadpool(_ingest)


@router.delete("/documents/{document_id}")
def delete_document(
    document_id: uuid.UUID,
    request: Request,
    admin: SessionUser = Depends(require_role(Role.ADMIN)),
) -> dict:
    with _session_factory(request)() as session:
        _service(request, session).delete(document_id)
        session.commit()
    return {"deleted": True}


@router.post("/search")
def search(
    body: SearchRequest,
    request: Request,
    admin: SessionUser = Depends(require_role(Role.ADMIN)),
) -> dict:
    with _session_factory(request)() as session:
        hits = _service(request, session).search(body.query)
    return {
        "hits": [
            {
                "document_id": str(h.document_id),
                "filename": h.filename,
                "content": h.content,
                "score": h.score,
            }
            for h in hits
        ]
    }


@router.post("/reindex")
def reindex(request: Request, admin: SessionUser = Depends(require_role(Role.ADMIN))) -> dict:
    with _session_factory(request)() as session:
        count = _service(request, session).reindex()
        session.commit()
    return {"documents": count}

