"""API tests for the knowledge-base admin routes."""
from __future__ import annotations

import asyncio
import io
import os

import pytest
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from testcontainers.postgres import PostgresContainer

from fsm.identity.domain.role import Role
from fsm.platform.api.kb_routes import MAX_UPLOAD_BYTES
from fsm.platform.app import create_app
from fsm.platform.config import Settings
from tests.assist.fakes import FakeDocumentIndex


@pytest.fixture(scope="module")
def pg_session_factory():
    with PostgresContainer("pgvector/pgvector:pg16", driver="psycopg") as pg:
        url = pg.get_connection_url()
        os.environ["DATABASE_URL"] = url
        cfg = AlembicConfig()
        cfg.set_main_option(
            "script_location",
            str(__import__("pathlib").Path(__file__).parents[3] / "alembic"),
        )
        cfg.set_main_option("sqlalchemy.url", url)
        alembic_command.upgrade(cfg, "head")
        engine = create_engine(url)
        yield sessionmaker(bind=engine, expire_on_commit=False)
        engine.dispose()
        del os.environ["DATABASE_URL"]


def _settings(database_url: str) -> Settings:
    return Settings(
        database_url=database_url,
        app_env="test",
        assist_embeddings="openai:text-embedding-3-small",
        openai_api_key="sk-test",  # enables the KB (embeddings provider = openai)
    )


def _app(pg_session_factory, enabled: bool = True):
    settings = (
        _settings(os.environ["DATABASE_URL"])
        if enabled
        else Settings(database_url=os.environ["DATABASE_URL"], app_env="test")
    )
    app = create_app(session_factory=pg_session_factory, settings=settings)
    if enabled:
        app.state.kb_index = FakeDocumentIndex()
    return app


def _upload(client, name: str = "guide.md", body: bytes = b"# Reset\nHold the button"):
    return client.post(
        "/api/kb/documents",
        files={"file": (name, io.BytesIO(body), "text/markdown")},
    )


class TestKbRoutes:
    def test_upload_list_search_delete_roundtrip(self, pg_session_factory, authenticate):
        app = _app(pg_session_factory)
        client = TestClient(app, follow_redirects=False)
        authenticate(app, role=Role.ADMIN)

        created = _upload(client)
        assert created.status_code == 201
        doc = created.json()
        assert doc["filename"] == "guide.md"
        assert doc["chunk_count"] >= 1
        assert set(doc["phase_seconds"]) == {"extract", "index"}
        assert all(
            isinstance(v, float) and v >= 0.0 for v in doc["phase_seconds"].values()
        )

        listed = client.get("/api/kb/documents")
        assert [d["id"] for d in listed.json()] == [doc["id"]]

        found = client.post("/api/kb/search", json={"query": "Reset"})
        assert found.status_code == 200
        assert found.json()["hits"][0]["document_id"] == doc["id"]

        deleted = client.delete(f"/api/kb/documents/{doc['id']}")
        assert deleted.status_code == 200
        assert deleted.json() == {"deleted": True}
        assert client.get("/api/kb/documents").json() == []

    def test_status_reports_enabled_and_model(self, pg_session_factory, authenticate):
        app = _app(pg_session_factory)
        client = TestClient(app, follow_redirects=False)
        authenticate(app, role=Role.ADMIN)
        status = client.get("/api/kb/status").json()
        assert status == {
            "enabled": True,
            "embedding_model": "openai:text-embedding-3-small",
            "needs_reindex": False,
        }

    def test_disabled_without_keys(self, pg_session_factory, authenticate):
        app = _app(pg_session_factory, enabled=False)
        client = TestClient(app, follow_redirects=False)
        authenticate(app, role=Role.ADMIN)
        assert client.get("/api/kb/status").json()["enabled"] is False
        assert client.get("/api/kb/documents").status_code == 503

    def test_non_admin_is_forbidden(self, pg_session_factory, authenticate):
        app = _app(pg_session_factory)
        client = TestClient(app, follow_redirects=False)
        authenticate(app, role=Role.CUSTOMER)
        assert client.get("/api/kb/documents").status_code == 403

    def test_unsupported_type_is_rejected(self, pg_session_factory, authenticate):
        app = _app(pg_session_factory)
        client = TestClient(app, follow_redirects=False)
        authenticate(app, role=Role.ADMIN)
        rejected = client.post(
            "/api/kb/documents",
            files={"file": ("photo.png", io.BytesIO(b"\x89PNG"), "image/png")},
        )
        assert rejected.status_code == 415

    def test_oversized_upload_is_rejected(self, pg_session_factory, authenticate):
        app = _app(pg_session_factory)
        client = TestClient(app, follow_redirects=False)
        authenticate(app, role=Role.ADMIN)
        big = b"a" * (MAX_UPLOAD_BYTES + 1)
        rejected = _upload(client, name="big.txt", body=big)
        assert rejected.status_code == 413

    def test_upload_ingests_off_the_event_loop(self, pg_session_factory, authenticate):
        """Extraction, embedding, and commit are synchronous work; running them on the event
        loop would stall every concurrent request on the process for the whole upload."""

        class LoopProbeIndex(FakeDocumentIndex):
            def __init__(self) -> None:
                super().__init__()
                self.ran_on_event_loop: bool | None = None

            def index_document(self, document_id, filename, text, on_progress=None) -> int:
                try:
                    asyncio.get_running_loop()
                    self.ran_on_event_loop = True
                except RuntimeError:
                    self.ran_on_event_loop = False
                return super().index_document(document_id, filename, text, on_progress)

        app = _app(pg_session_factory)
        app.state.kb_index = LoopProbeIndex()
        client = TestClient(app, follow_redirects=False)
        authenticate(app, role=Role.ADMIN)
        assert _upload(client).status_code == 201
        assert app.state.kb_index.ran_on_event_loop is False
