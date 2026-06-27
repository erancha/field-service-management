"""Integration tests for the identity persistence layer against real Postgres.

A Postgres 16 container is started once per module via testcontainers. Alembic
migrations (0001 + 0002) are applied, then each test runs inside its own
savepoint that is rolled back after the test.
"""
from __future__ import annotations

import os
import uuid

import pytest
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from testcontainers.postgres import PostgresContainer

import datetime as dt

from fsm.identity.adapters.repositories import SqlAlchemyUserRepository
from fsm.identity.domain.errors import DuplicateGoogleSub, NotFoundError
from fsm.identity.domain.role import Role
from fsm.identity.domain.role_status import RoleStatus
from fsm.identity.domain.user import User


def _make_user(
    *,
    google_sub: str = "sub-001",
    role: Role = Role.CUSTOMER,
    role_status: RoleStatus = RoleStatus.APPROVED,
) -> User:
    return User(
        id=uuid.uuid4(),
        google_sub=google_sub,
        email=f"{google_sub}@example.com",
        name="Test User",
        role=role,
        role_status=role_status,
    )


@pytest.fixture(scope="module")
def pg_engine():
    with PostgresContainer("postgres:16", driver="psycopg") as pg:
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
        yield engine
        engine.dispose()

        del os.environ["DATABASE_URL"]


@pytest.fixture
def session(pg_engine):
    """Yield a session inside a savepoint; roll back after each test."""
    Session = sessionmaker(bind=pg_engine, expire_on_commit=False)
    with Session() as sess:
        with sess.begin():
            sess.begin_nested()
            yield sess
            sess.rollback()


class TestSqlAlchemyUserRepository:
    def test_add_then_get_by_google_sub_round_trips(self, session):
        repo = SqlAlchemyUserRepository(session)
        user = _make_user(google_sub="sub-roundtrip")
        repo.add(user)
        fetched = repo.get_by_google_sub("sub-roundtrip")
        assert fetched is not None
        assert fetched.id == user.id
        assert fetched.google_sub == user.google_sub
        assert fetched.email == user.email
        assert fetched.name == user.name
        assert fetched.role == user.role

    def test_get_by_google_sub_unknown_returns_none(self, session):
        repo = SqlAlchemyUserRepository(session)
        assert repo.get_by_google_sub("no-such-sub") is None

    def test_get_by_id_raises_not_found_for_unknown_id(self, session):
        repo = SqlAlchemyUserRepository(session)
        with pytest.raises(NotFoundError):
            repo.get(uuid.uuid4())

    def test_save_persists_role_promotion(self, session):
        repo = SqlAlchemyUserRepository(session)
        user = _make_user(google_sub="sub-promote", role=Role.CUSTOMER)
        repo.add(user)
        user.request_role(Role.TECHNICIAN)
        repo.save(user)
        fetched = repo.get(user.id)
        assert fetched.role == Role.TECHNICIAN

    def test_role_status_and_decision_stamps_round_trip(self, session):
        repo = SqlAlchemyUserRepository(session)
        admin_id = uuid.uuid4()
        decided_at = dt.datetime(2026, 6, 26, 12, 0, tzinfo=dt.timezone.utc)
        user = _make_user(
            google_sub="sub-pending", role=Role.TECHNICIAN, role_status=RoleStatus.PENDING
        )
        repo.add(user)
        user.approve(decided_by=admin_id, at=decided_at)
        repo.save(user)

        fetched = repo.get(user.id)
        assert fetched.role_status == RoleStatus.APPROVED
        assert fetched.role_decided_by == admin_id
        assert fetched.role_decided_at == decided_at

    def test_list_pending_technicians_returns_only_pending_technicians(self, session):
        repo = SqlAlchemyUserRepository(session)
        pending = _make_user(
            google_sub="sub-q-pending", role=Role.TECHNICIAN, role_status=RoleStatus.PENDING
        )
        approved = _make_user(
            google_sub="sub-q-approved", role=Role.TECHNICIAN, role_status=RoleStatus.APPROVED
        )
        customer = _make_user(google_sub="sub-q-customer", role=Role.CUSTOMER)
        for u in (pending, approved, customer):
            repo.add(u)

        result = repo.list_pending_technicians()

        assert [u.id for u in result] == [pending.id]

    def test_duplicate_google_sub_raises_duplicate_google_sub(self, session):
        repo = SqlAlchemyUserRepository(session)
        user1 = _make_user(google_sub="sub-dup")
        user2 = _make_user(google_sub="sub-dup")
        repo.add(user1)
        with pytest.raises(DuplicateGoogleSub):
            repo.add(user2)
