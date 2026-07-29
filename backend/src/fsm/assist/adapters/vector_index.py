"""DocumentIndex adapter over LangChain's PGVectorStore (pgvector in Postgres).

The store owns its chunk table (created lazily, sized to the injected embedding model).
Chunk ids are deterministic uuid5 values derived from (document id, chunk index), so a
document's chunks can be deleted knowing only how many were written.
"""
from __future__ import annotations

import uuid

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_postgres import PGEngine, PGVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy import create_engine, inspect

from fsm.assist.ports.document_index import SearchHit

_CHUNK_NAMESPACE = uuid.UUID("aeb60731-5f5f-4a91-9e2b-2f4bfd7c2a11")


def _chunk_id(document_id: uuid.UUID, chunk_index: int) -> str:
    return str(uuid.uuid5(_CHUNK_NAMESPACE, f"{document_id}:{chunk_index}"))


class PgVectorDocumentIndex:
    def __init__(
        self,
        connection_url: str,
        embeddings: Embeddings,
        *,
        table_name: str = "kb_chunk",
    ) -> None:
        self._url = connection_url
        self._embeddings = embeddings
        self._table_name = table_name
        self._engine = PGEngine.from_connection_string(url=connection_url)
        self._splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
        self._store: PGVectorStore | None = None

    def _table_exists(self) -> bool:
        sync_engine = create_engine(self._url)
        try:
            return inspect(sync_engine).has_table(self._table_name)
        finally:
            sync_engine.dispose()

    def _get_store(self) -> PGVectorStore:
        if self._store is None:
            if not self._table_exists():
                # Vector width is a property of the embedding model; probe it once.
                vector_size = len(self._embeddings.embed_query("dimension probe"))
                self._engine.init_vectorstore_table(
                    table_name=self._table_name, vector_size=vector_size
                )
            self._store = PGVectorStore.create_sync(
                engine=self._engine,
                table_name=self._table_name,
                embedding_service=self._embeddings,
            )
        return self._store

    def index_document(self, document_id: uuid.UUID, filename: str, text: str) -> int:
        chunks = self._splitter.split_text(text)
        documents = [
            Document(
                page_content=chunk,
                metadata={
                    "document_id": str(document_id),
                    "filename": filename,
                    "chunk_index": i,
                },
            )
            for i, chunk in enumerate(chunks)
        ]
        ids = [_chunk_id(document_id, i) for i in range(len(chunks))]
        self._get_store().add_documents(documents, ids=ids)
        return len(chunks)

    def remove_document(self, document_id: uuid.UUID, chunk_count: int) -> None:
        if chunk_count == 0:
            return
        ids = [_chunk_id(document_id, i) for i in range(chunk_count)]
        self._get_store().delete(ids)

    def search(self, query: str, limit: int) -> list[SearchHit]:
        if not self._table_exists():
            return []
        results = self._get_store().similarity_search_with_score(query, k=limit)
        return [
            SearchHit(
                document_id=uuid.UUID(doc.metadata["document_id"]),
                filename=doc.metadata["filename"],
                content=doc.page_content,
                # The store returns cosine distance; similarity = 1 - distance.
                score=1.0 - distance,
            )
            for doc, distance in results
        ]

    def reset(self) -> None:
        if self._table_exists():
            self._engine.drop_table(self._table_name)
        self._store = None
