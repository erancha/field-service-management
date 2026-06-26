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

    with PostgresContainer("postgres:16", driver="psycopg") as pg:
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


class TestSqlAlchemyNotificationFeedRepository:
    def test_add_and_list_for_user(self, session):
        from fsm.notifications.adapters.feed_repository import SqlAlchemyNotificationFeedRepository
        from fsm.notifications.domain.notification import Notification, NotificationKind

        repo = SqlAlchemyNotificationFeedRepository(session)
        user_id = uuid.uuid4()
        notification = Notification(
            id=uuid.uuid4(),
            user_id=user_id,
            kind=NotificationKind.BOOKED,
            subject="Test subject",
            body="Test body",
            created_at=datetime(2025, 6, 10, 9, 0, tzinfo=timezone.utc),
        )

        repo.add(notification)
        session.flush()

        results = repo.list_for_user(user_id)
        assert len(results) == 1
        assert results[0].user_id == user_id
        assert results[0].kind == NotificationKind.BOOKED
        assert results[0].read is False

    def test_list_for_user_excludes_other_users(self, session):
        from fsm.notifications.adapters.feed_repository import SqlAlchemyNotificationFeedRepository
        from fsm.notifications.domain.notification import Notification, NotificationKind

        repo = SqlAlchemyNotificationFeedRepository(session)
        user_a = uuid.uuid4()
        user_b = uuid.uuid4()

        repo.add(Notification(
            id=uuid.uuid4(),
            user_id=user_a,
            kind=NotificationKind.BOOKED,
            subject="For A",
            body="body",
            created_at=datetime(2025, 6, 10, 9, 0, tzinfo=timezone.utc),
        ))
        session.flush()

        results = repo.list_for_user(user_b)
        assert results == []

    def test_unread_only_filter(self, session):
        from fsm.notifications.adapters.feed_repository import SqlAlchemyNotificationFeedRepository
        from fsm.notifications.domain.notification import Notification, NotificationKind

        repo = SqlAlchemyNotificationFeedRepository(session)
        user_id = uuid.uuid4()
        n_unread = Notification(
            id=uuid.uuid4(),
            user_id=user_id,
            kind=NotificationKind.BOOKED,
            subject="Unread",
            body="body",
            created_at=datetime(2025, 6, 10, 9, 0, tzinfo=timezone.utc),
            read=False,
        )
        n_read = Notification(
            id=uuid.uuid4(),
            user_id=user_id,
            kind=NotificationKind.CANCELLED,
            subject="Read",
            body="body",
            created_at=datetime(2025, 6, 10, 10, 0, tzinfo=timezone.utc),
            read=True,
        )
        repo.add(n_unread)
        repo.add(n_read)
        session.flush()

        unread_results = repo.list_for_user(user_id, unread_only=True)
        assert len(unread_results) == 1
        assert unread_results[0].subject == "Unread"

        all_results = repo.list_for_user(user_id)
        assert len(all_results) == 2

    def test_mark_read(self, session):
        from fsm.notifications.adapters.feed_repository import SqlAlchemyNotificationFeedRepository
        from fsm.notifications.domain.notification import Notification, NotificationKind

        repo = SqlAlchemyNotificationFeedRepository(session)
        user_id = uuid.uuid4()
        notif_id = uuid.uuid4()
        notification = Notification(
            id=notif_id,
            user_id=user_id,
            kind=NotificationKind.RESCHEDULED,
            subject="Reschedule",
            body="body",
            created_at=datetime(2025, 6, 10, 9, 0, tzinfo=timezone.utc),
        )
        repo.add(notification)
        session.flush()

        results_before = repo.list_for_user(user_id, unread_only=True)
        assert len(results_before) == 1

        repo.mark_read(notif_id)
        session.flush()

        results_after = repo.list_for_user(user_id, unread_only=True)
        assert len(results_after) == 0

        all_results = repo.list_for_user(user_id)
        assert len(all_results) == 1
        assert all_results[0].read is True
