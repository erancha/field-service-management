"""Tests for the worker deployment's composition: leadership policy and startup checks.

The lease is a port, so the standby-and-take-over policy is exercised with a fake here; that a
real Postgres lease excludes a second holder is covered in test_sync_runner.py.
"""
from __future__ import annotations

import threading

import pytest

from fsm.platform.config import Settings
from fsm.platform.worker import run_sync_under_lease


class FakeLease:
    """Lease that grants the hold after a set number of refusals, recording every call."""

    def __init__(self, refusals: int = 0) -> None:
        self.refusals = refusals
        self.acquired = 0
        self.released = 0

    def acquire(self) -> bool:
        if self.refusals > 0:
            self.refusals -= 1
            return False
        self.acquired += 1
        return True

    def release(self) -> None:
        self.released += 1


def _stop_after_one_poll(stop_event: threading.Event):
    """Return a poll loop that records its calls and stops the worker, as run_forever would."""
    calls: list[int] = []

    def poll_loop() -> None:
        calls.append(1)
        stop_event.set()

    return poll_loop, calls


def test_polls_while_it_holds_the_lease():
    stop = threading.Event()
    lease = FakeLease()
    poll_loop, calls = _stop_after_one_poll(stop)

    run_sync_under_lease(lease, poll_loop, stop, retry_seconds=0.01)

    assert calls == [1]
    assert lease.released == 1


def test_stands_by_until_the_lease_frees_up():
    """A losing process keeps trying, so a dead holder is replaced without operator action."""
    stop = threading.Event()
    lease = FakeLease(refusals=3)
    poll_loop, calls = _stop_after_one_poll(stop)

    run_sync_under_lease(lease, poll_loop, stop, retry_seconds=0.01)

    assert calls == [1]
    assert lease.acquired == 1


def test_stops_while_standing_by_without_ever_polling():
    stop = threading.Event()
    stop.set()
    lease = FakeLease(refusals=1)
    poll_loop, calls = _stop_after_one_poll(stop)

    run_sync_under_lease(lease, poll_loop, stop, retry_seconds=0.01)

    assert calls == []
    assert lease.released == 0


def test_releases_the_lease_when_the_poll_loop_raises():
    stop = threading.Event()
    lease = FakeLease()

    def exploding_loop() -> None:
        raise RuntimeError("poll loop failed")

    with pytest.raises(RuntimeError, match="poll loop failed"):
        run_sync_under_lease(lease, exploding_loop, stop, retry_seconds=0.01)

    assert lease.released == 1


def test_worker_refuses_dispatch_without_the_technician_app_url():
    """Checked before the thread spawns: a raise inside it would leave the worker half-running."""
    from fsm.platform.worker import start_workers

    settings = Settings(
        database_url="postgresql+psycopg://fsm:fsm@localhost:5432/fsm",
        app_env="test",
        fsm_role="worker",
        technician_app_url=None,
    )

    with pytest.raises(ValueError, match="technician_app_url"):
        start_workers(lambda: None, settings, threading.Event(), publish=None)
