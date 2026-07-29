"""Customer triage chat over HTTP, with a fake chat model and a real Postgres schema."""
from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from fsm.assist.application.prompts import CLOSED_MARKER, ESCALATE_MARKER, SOLVED_MARKER
from fsm.identity.domain.role import Role
from fsm.platform.api.triage_routes import MAX_MESSAGE_CHARS
from fsm.platform.app import create_app
from fsm.platform.config import Settings
from fsm.scheduling.adapters.orm import ServiceCallRow
from fsm.scheduling.adapters.repositories import SqlAlchemyServiceCallRepository
from tests.assist.fakes import FakeChatModel, FakeDocumentIndex


OVEN_DOC = "The oven will not heat. Hold the reset button behind the lower panel for ten seconds."


@pytest.fixture(scope="module")
def pg_session_factory(pg_engine):
    """Sessions over the shared migrated database; `pg_engine` lives in the root conftest."""
    return sessionmaker(bind=pg_engine)


def build_app(pg_session_factory, chat_model, *, enabled: bool = True):
    settings = Settings(
        assist_model="anthropic:claude-sonnet-5" if enabled else None,
        anthropic_api_key="sk-test" if enabled else None,
        database_url="postgresql+psycopg://u:p@localhost/db",
    )
    app = create_app(session_factory=pg_session_factory, settings=settings)
    app.state.assist_chat_model = chat_model
    return app


def read_sse(response) -> list[tuple[str, dict]]:
    frames: list[tuple[str, dict]] = []
    event = None
    for line in response.text.splitlines():
        if line.startswith("event: "):
            event = line.removeprefix("event: ")
        elif line.startswith("data: ") and event is not None:
            frames.append((event, json.loads(line.removeprefix("data: "))))
    return frames


class TestTriageRoutes:
    def test_status_reports_enabled_when_configured(self, pg_session_factory, authenticate):
        app = build_app(pg_session_factory, FakeChatModel())
        authenticate(app, role=Role.CUSTOMER)

        with TestClient(app) as client:
            response = client.get("/api/assist/status")

        assert response.status_code == 200
        assert response.json() == {"enabled": True}

    def test_status_reports_disabled_without_keys(self, pg_session_factory, authenticate):
        app = build_app(pg_session_factory, None, enabled=False)
        authenticate(app, role=Role.CUSTOMER)

        with TestClient(app) as client:
            response = client.get("/api/assist/status")

        assert response.json() == {"enabled": False}

    def test_status_requires_a_session(self, pg_session_factory):
        app = build_app(pg_session_factory, FakeChatModel())

        with TestClient(app) as client:
            assert client.get("/api/assist/status").status_code == 401

    def test_conversation_routes_are_unavailable_when_disabled(
        self, pg_session_factory, authenticate
    ):
        app = build_app(pg_session_factory, None, enabled=False)
        authenticate(app, role=Role.CUSTOMER)

        with TestClient(app) as client:
            assert client.post("/api/assist/conversations").status_code == 503

    def test_technicians_cannot_open_a_triage_conversation(
        self, pg_session_factory, authenticate
    ):
        app = build_app(pg_session_factory, FakeChatModel())
        authenticate(app, role=Role.TECHNICIAN)

        with TestClient(app) as client:
            assert client.post("/api/assist/conversations").status_code == 403

    def test_starting_twice_returns_the_same_conversation(
        self, pg_session_factory, authenticate
    ):
        app = build_app(pg_session_factory, FakeChatModel())
        authenticate(app, role=Role.CUSTOMER)

        with TestClient(app) as client:
            first = client.post("/api/assist/conversations").json()
            second = client.post("/api/assist/conversations").json()

        assert first["id"] == second["id"]
        assert first["status"] == "ACTIVE"
        assert first["messages"] == []

    def test_a_turn_streams_tokens_and_survives_a_reload(
        self, pg_session_factory, authenticate
    ):
        app = build_app(pg_session_factory, FakeChatModel(replies=["Is the display lit?"]))
        authenticate(app, role=Role.CUSTOMER)

        with TestClient(app) as client:
            conversation_id = client.post("/api/assist/conversations").json()["id"]
            stream = client.post(
                f"/api/assist/conversations/{conversation_id}/messages",
                json={"text": "The oven will not heat."},
            )
            reloaded = client.get(f"/api/assist/conversations/{conversation_id}").json()

        assert stream.status_code == 200
        assert stream.headers["content-type"].startswith("text/event-stream")
        frames = read_sse(stream)
        tokens = "".join(payload["text"] for event, payload in frames if event == "token")
        assert tokens.strip() == "Is the display lit?"
        assert [(m["role"], m["text"]) for m in reloaded["messages"]] == [
            ("CUSTOMER", "The oven will not heat."),
            ("ASSISTANT", "Is the display lit?"),
        ]

    def test_a_solved_ending_creates_no_service_call(self, pg_session_factory, authenticate):
        app = build_app(
            pg_session_factory, FakeChatModel(replies=[f"Glad that worked. {SOLVED_MARKER}"])
        )
        customer_id = authenticate(app, role=Role.CUSTOMER)

        with TestClient(app) as client:
            conversation_id = client.post("/api/assist/conversations").json()["id"]
            stream = client.post(
                f"/api/assist/conversations/{conversation_id}/messages",
                json={"text": "That fixed it."},
            )

        done = [payload for event, payload in read_sse(stream) if event == "done"][0]
        assert done["status"] == "SOLVED"
        assert done["service_call"] is None

        with pg_session_factory() as session:
            opened = session.scalars(
                select(ServiceCallRow).where(ServiceCallRow.customer_id == customer_id)
            ).all()
        assert opened == []

    def test_an_escalation_opens_a_service_call_carrying_the_summary(
        self, pg_session_factory, authenticate
    ):
        chat_model = FakeChatModel(replies=[f"I will book a technician. {ESCALATE_MARKER}"])
        app = build_app(pg_session_factory, chat_model)
        customer_id = authenticate(app, role=Role.CUSTOMER)

        with TestClient(app) as client:
            conversation_id = client.post("/api/assist/conversations").json()["id"]
            stream = client.post(
                f"/api/assist/conversations/{conversation_id}/messages",
                json={"text": "Still cold after all that."},
            )

        done = [payload for event, payload in read_sse(stream) if event == "done"][0]
        assert done["status"] == "ESCALATED"
        assert done["service_call"]["description"] == chat_model.summary.render()

        with pg_session_factory() as session:
            stored = SqlAlchemyServiceCallRepository(session).get(
                uuid.UUID(done["service_call"]["id"])
            )
        assert stored.customer_id == customer_id
        assert stored.status.value == "OPEN"

    def test_a_closed_ending_creates_no_service_call(self, pg_session_factory, authenticate):
        app = build_app(
            pg_session_factory,
            FakeChatModel(replies=[f"That is not something I can help with. {CLOSED_MARKER}"]),
        )
        customer_id = authenticate(app, role=Role.CUSTOMER)

        with TestClient(app) as client:
            conversation_id = client.post("/api/assist/conversations").json()["id"]
            stream = client.post(
                f"/api/assist/conversations/{conversation_id}/messages",
                json={"text": "Please close this chat."},
            )

        done = [payload for event, payload in read_sse(stream) if event == "done"][0]
        assert done["status"] == "ABANDONED"
        assert done["service_call"] is None

        with pg_session_factory() as session:
            opened = session.scalars(
                select(ServiceCallRow).where(ServiceCallRow.customer_id == customer_id)
            ).all()
        assert opened == []

    def test_a_turn_is_grounded_in_the_knowledge_base_the_app_holds(
        self, pg_session_factory, authenticate
    ):
        chat_model = FakeChatModel(replies=["Hold the reset button."])
        app = build_app(pg_session_factory, chat_model)
        index = FakeDocumentIndex()
        index.index_document(uuid.uuid4(), "oven-guide.md", OVEN_DOC)
        app.state.kb_index = index
        authenticate(app, role=Role.CUSTOMER)

        with TestClient(app) as client:
            conversation_id = client.post("/api/assist/conversations").json()["id"]
            client.post(
                f"/api/assist/conversations/{conversation_id}/messages",
                json={"text": "The oven will not heat."},
            )

        system, _ = chat_model.stream_calls[0]
        assert "oven-guide.md" in system
        assert OVEN_DOC in system

    def test_ending_a_conversation_abandons_it_without_a_service_call(
        self, pg_session_factory, authenticate
    ):
        app = build_app(pg_session_factory, FakeChatModel())
        customer_id = authenticate(app, role=Role.CUSTOMER)

        with TestClient(app) as client:
            conversation_id = client.post("/api/assist/conversations").json()["id"]
            ended = client.post(f"/api/assist/conversations/{conversation_id}/end")

        assert ended.status_code == 200
        assert ended.json()["status"] == "ABANDONED"
        assert ended.json()["service_call_id"] is None

        with pg_session_factory() as session:
            opened = session.scalars(
                select(ServiceCallRow).where(ServiceCallRow.customer_id == customer_id)
            ).all()
        assert opened == []

    def test_ending_an_already_ended_conversation_is_rejected(
        self, pg_session_factory, authenticate
    ):
        app = build_app(pg_session_factory, FakeChatModel())
        authenticate(app, role=Role.CUSTOMER)

        with TestClient(app) as client:
            conversation_id = client.post("/api/assist/conversations").json()["id"]
            client.post(f"/api/assist/conversations/{conversation_id}/end")
            rejected = client.post(f"/api/assist/conversations/{conversation_id}/end")

        assert rejected.status_code == 409

    def test_an_ended_conversation_rejects_further_messages(
        self, pg_session_factory, authenticate
    ):
        app = build_app(pg_session_factory, FakeChatModel())
        authenticate(app, role=Role.CUSTOMER)

        with TestClient(app) as client:
            conversation_id = client.post("/api/assist/conversations").json()["id"]
            client.post(f"/api/assist/conversations/{conversation_id}/end")
            rejected = client.post(
                f"/api/assist/conversations/{conversation_id}/messages",
                json={"text": "Actually, one more thing."},
            )

        assert rejected.status_code == 409

    def test_another_customer_cannot_end_the_conversation(
        self, pg_session_factory, authenticate
    ):
        app = build_app(pg_session_factory, FakeChatModel())
        authenticate(app, role=Role.CUSTOMER)

        with TestClient(app) as client:
            conversation_id = client.post("/api/assist/conversations").json()["id"]

        authenticate(app, user_id=uuid.uuid4(), role=Role.CUSTOMER)
        with TestClient(app) as client:
            rejected = client.post(f"/api/assist/conversations/{conversation_id}/end")

        assert rejected.status_code == 404

    def test_technicians_cannot_end_a_conversation(self, pg_session_factory, authenticate):
        app = build_app(pg_session_factory, FakeChatModel())
        authenticate(app, role=Role.CUSTOMER)

        with TestClient(app) as client:
            conversation_id = client.post("/api/assist/conversations").json()["id"]

        authenticate(app, role=Role.TECHNICIAN)
        with TestClient(app) as client:
            assert (
                client.post(f"/api/assist/conversations/{conversation_id}/end").status_code == 403
            )

    def test_a_closed_conversation_rejects_further_messages(
        self, pg_session_factory, authenticate
    ):
        app = build_app(pg_session_factory, FakeChatModel(replies=[f"Done. {SOLVED_MARKER}"]))
        authenticate(app, role=Role.CUSTOMER)

        with TestClient(app) as client:
            conversation_id = client.post("/api/assist/conversations").json()["id"]
            client.post(
                f"/api/assist/conversations/{conversation_id}/messages",
                json={"text": "Fixed."},
            )
            rejected = client.post(
                f"/api/assist/conversations/{conversation_id}/messages",
                json={"text": "One more thing."},
            )

        assert rejected.status_code == 409

    def test_another_customer_cannot_read_the_conversation(
        self, pg_session_factory, authenticate
    ):
        app = build_app(pg_session_factory, FakeChatModel())
        authenticate(app, role=Role.CUSTOMER)

        with TestClient(app) as client:
            conversation_id = client.post("/api/assist/conversations").json()["id"]

        authenticate(app, user_id=uuid.uuid4(), role=Role.CUSTOMER)
        with TestClient(app) as client:
            assert client.get(f"/api/assist/conversations/{conversation_id}").status_code == 404

    def test_another_customer_cannot_send_a_message(self, pg_session_factory, authenticate):
        """A stranger's conversation is reported absent, not forbidden, so ids do not leak."""
        app = build_app(pg_session_factory, FakeChatModel())
        authenticate(app, role=Role.CUSTOMER)

        with TestClient(app) as client:
            conversation_id = client.post("/api/assist/conversations").json()["id"]

        authenticate(app, user_id=uuid.uuid4(), role=Role.CUSTOMER)
        with TestClient(app) as client:
            rejected = client.post(
                f"/api/assist/conversations/{conversation_id}/messages",
                json={"text": "Let me read someone else's thread."},
            )

        assert rejected.status_code == 404

    def test_technicians_cannot_read_a_conversation(self, pg_session_factory, authenticate):
        app = build_app(pg_session_factory, FakeChatModel())
        authenticate(app, role=Role.CUSTOMER)

        with TestClient(app) as client:
            conversation_id = client.post("/api/assist/conversations").json()["id"]

        authenticate(app, role=Role.TECHNICIAN)
        with TestClient(app) as client:
            assert client.get(f"/api/assist/conversations/{conversation_id}").status_code == 403

    def test_technicians_cannot_send_a_message(self, pg_session_factory, authenticate):
        app = build_app(pg_session_factory, FakeChatModel())
        authenticate(app, role=Role.CUSTOMER)

        with TestClient(app) as client:
            conversation_id = client.post("/api/assist/conversations").json()["id"]

        authenticate(app, role=Role.TECHNICIAN)
        with TestClient(app) as client:
            rejected = client.post(
                f"/api/assist/conversations/{conversation_id}/messages",
                json={"text": "Answering on the customer's behalf."},
            )

        assert rejected.status_code == 403

    def test_an_overlong_message_is_rejected(self, pg_session_factory, authenticate):
        """The model and the store are shielded from unbounded input on an unthrottled endpoint."""
        app = build_app(pg_session_factory, FakeChatModel())
        authenticate(app, role=Role.CUSTOMER)

        with TestClient(app) as client:
            conversation_id = client.post("/api/assist/conversations").json()["id"]
            response = client.post(
                f"/api/assist/conversations/{conversation_id}/messages",
                json={"text": "x" * (MAX_MESSAGE_CHARS + 1)},
            )

        assert response.status_code == 422

    def test_an_empty_message_is_rejected(self, pg_session_factory, authenticate):
        app = build_app(pg_session_factory, FakeChatModel())
        authenticate(app, role=Role.CUSTOMER)

        with TestClient(app) as client:
            conversation_id = client.post("/api/assist/conversations").json()["id"]
            response = client.post(
                f"/api/assist/conversations/{conversation_id}/messages", json={"text": "   "}
            )

        assert response.status_code == 422

    def test_history_lists_ended_conversations_and_skips_the_live_empty_one(
        self, pg_session_factory, authenticate
    ):
        app = build_app(pg_session_factory, FakeChatModel(replies=[f"Done. {SOLVED_MARKER}"]))
        authenticate(app, role=Role.CUSTOMER)

        with TestClient(app) as client:
            solved_id = client.post("/api/assist/conversations").json()["id"]
            client.post(
                f"/api/assist/conversations/{solved_id}/messages",
                json={"text": "The oven will not heat."},
            )
            client.post("/api/assist/conversations")
            history = client.get("/api/assist/conversations").json()

        assert [
            (c["id"], c["status"], c["opening_line"]) for c in history["conversations"]
        ] == [(solved_id, "SOLVED", "The oven will not heat.")]

    def test_history_carries_no_conversations_of_other_customers(
        self, pg_session_factory, authenticate
    ):
        app = build_app(pg_session_factory, FakeChatModel(replies=[f"Done. {SOLVED_MARKER}"]))
        authenticate(app, role=Role.CUSTOMER)
        with TestClient(app) as client:
            conversation_id = client.post("/api/assist/conversations").json()["id"]
            client.post(
                f"/api/assist/conversations/{conversation_id}/messages", json={"text": "Cold."}
            )

        authenticate(app, role=Role.CUSTOMER)
        with TestClient(app) as client:
            assert client.get("/api/assist/conversations").json() == {"conversations": []}

    def test_technicians_cannot_read_the_triage_history(self, pg_session_factory, authenticate):
        app = build_app(pg_session_factory, FakeChatModel())
        authenticate(app, role=Role.TECHNICIAN)

        with TestClient(app) as client:
            assert client.get("/api/assist/conversations").status_code == 403
