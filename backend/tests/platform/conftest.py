"""Fixtures shared by the tests that compose an app from a role.

A deployment's workers come with its role (fsm/platform/roles.py), so any test building a
backoffice app starts them; this is where those tests get an idle stand-in for the loops.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def stubbed_worker_runners(monkeypatch):
    """Replace both worker loops with an idle wait so tests exercise app wiring, not the runners."""
    import fsm.platform.dispatcher_runner as dispatcher_runner
    import fsm.platform.sync_runner as sync_runner

    def idle_runner(session_factory, settings, stop_event, publish=None):
        stop_event.wait()

    monkeypatch.setattr(dispatcher_runner, "run_forever", idle_runner)
    monkeypatch.setattr(sync_runner, "run_forever", idle_runner)
