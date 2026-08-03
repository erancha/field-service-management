"""Tests for generic engine construction.

Building an engine contacts no server, so these run without a database; that an FSM engine really
connects and executes is covered in tests/platform/test_db.py.
"""
from __future__ import annotations

from fsm.core.db import build_engine, session_factory

_URL = "postgresql+psycopg://user:pass@localhost:5432/db"


def test_engine_holds_the_pool_the_caller_asked_for():
    engine = build_engine(_URL, pool_size=3, max_overflow=1)

    assert engine.pool.size() == 3


def test_sessions_stay_readable_after_commit():
    factory = session_factory(build_engine(_URL, pool_size=1, max_overflow=0))

    assert factory.kw["expire_on_commit"] is False
