"""Integration tests for SqlAlchemyNotificationFeedRepository against real Postgres."""
from __future__ import annotations

import os
import pathlib
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture(scope="module")
def pg_engine():
    from alembic import command as alembic_command
    from alembic.config import Config as AlembicConfig
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("pgvector/pgvector:pg16", driver="psycopg") as pg:
        url = pg.get_connection_url()
        os.environ["DATABASE_URL"] = url

        cfg = AlembicConfig()
        cfg.set_main_option(
            "script_location",
            str(pathlib.Path(__file__).parents[3] / "alembic"),
        )
        cfg.set_main_option("sqlalchemy.url", url)
        alembic_command.upgrade(cfg, "head")

        engine = create_engine(url)
        yield engine
        engine.dispose()
        del os.environ["DATABASE_URL"]


@pytest.fixture
def session(pg_engine):
    factory = sessionmaker(bind=pg_engine, expire_on_commit=False)
    with factory() as sess:
        yield sess
        sess.rollback()


def _event(kind, subject="Test subject", body="Test body", at_hour=9):
    from fsm.notifications.domain.notification import NotificationEvent

    return NotificationEvent(
        id=uuid.uuid4(),
        kind=kind,
        subject=subject,
        body=body,
        created_at=datetime(2025, 6, 10, at_hour, 0, tzinfo=timezone.utc),
    )


class TestSqlAlchemyNotificationFeedRepository:
    def test_add_event_and_list_for_user(self, session):
        from fsm.notifications.adapters.feed_repository import SqlAlchemyNotificationFeedRepository
        from fsm.notifications.domain.notification import NotificationKind

        repo = SqlAlchemyNotificationFeedRepository(session)
        user_id = uuid.uuid4()

        repo.add_event(_event(NotificationKind.BOOKED), [user_id])
        session.flush()

        results = repo.list_for_user(user_id)
        assert len(results) == 1
        assert results[0].user_id == user_id
        assert results[0].kind == NotificationKind.BOOKED
        assert results[0].subject == "Test subject"
        assert results[0].body == "Test body"
        assert results[0].read is False

    def test_shared_event_stores_content_once_across_recipients(self, session):
        from fsm.notifications.adapters.feed_repository import SqlAlchemyNotificationFeedRepository
        from fsm.notifications.adapters.orm import NotificationEventRow, NotificationRecipientRow
        from fsm.notifications.domain.notification import NotificationKind

        repo = SqlAlchemyNotificationFeedRepository(session)
        customer_id = uuid.uuid4()
        technician_id = uuid.uuid4()

        repo.add_event(_event(NotificationKind.BOOKED), [customer_id, technician_id])
        session.flush()

        event_id = session.query(NotificationEventRow.id).scalar()
        recipient_rows = (
            session.query(NotificationRecipientRow)
            .filter(NotificationRecipientRow.notification_event_id == event_id)
            .all()
        )
        assert session.query(NotificationEventRow).count() == 1
        assert {r.user_id for r in recipient_rows} == {customer_id, technician_id}

        for user_id in (customer_id, technician_id):
            [seen] = repo.list_for_user(user_id)
            assert seen.subject == "Test subject"
            assert seen.body == "Test body"

    def test_list_for_user_excludes_other_users(self, session):
        from fsm.notifications.adapters.feed_repository import SqlAlchemyNotificationFeedRepository
        from fsm.notifications.domain.notification import NotificationKind

        repo = SqlAlchemyNotificationFeedRepository(session)
        user_a = uuid.uuid4()
        user_b = uuid.uuid4()

        repo.add_event(_event(NotificationKind.BOOKED, subject="For A"), [user_a])
        session.flush()

        assert repo.list_for_user(user_b) == []

    def test_unread_only_filter(self, session):
        from fsm.notifications.adapters.feed_repository import SqlAlchemyNotificationFeedRepository
        from fsm.notifications.domain.notification import NotificationKind

        repo = SqlAlchemyNotificationFeedRepository(session)
        user_id = uuid.uuid4()

        repo.add_event(_event(NotificationKind.BOOKED, subject="Unread"), [user_id])
        read_event = _event(NotificationKind.CANCELLED, subject="Read", at_hour=10)
        repo.add_event(read_event, [user_id])
        session.flush()

        [read_row] = [n for n in repo.list_for_user(user_id) if n.subject == "Read"]
        repo.mark_read(read_row.id)
        session.flush()

        unread_results = repo.list_for_user(user_id, unread_only=True)
        assert len(unread_results) == 1
        assert unread_results[0].subject == "Unread"

        assert len(repo.list_for_user(user_id)) == 2

    def test_mark_read_flips_only_the_targeted_recipient(self, session):
        from fsm.notifications.adapters.feed_repository import SqlAlchemyNotificationFeedRepository
        from fsm.notifications.domain.notification import NotificationKind

        repo = SqlAlchemyNotificationFeedRepository(session)
        customer_id = uuid.uuid4()
        technician_id = uuid.uuid4()

        repo.add_event(_event(NotificationKind.RESCHEDULED), [customer_id, technician_id])
        session.flush()

        [customer_row] = repo.list_for_user(customer_id)
        repo.mark_read(customer_row.id)
        session.flush()

        assert repo.list_for_user(customer_id, unread_only=True) == []
        assert repo.list_for_user(customer_id)[0].read is True
        assert len(repo.list_for_user(technician_id, unread_only=True)) == 1
