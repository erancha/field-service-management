"""Tests that FSM processes read their log levels from the FSM_ environment variables.

The behaviour behind them is covered in tests/core/test_logging.py; what matters here is only
which prefix the platform entry point binds.
"""
from __future__ import annotations

import logging

import pytest
import structlog

from fsm.platform.logging import configure_logging


@pytest.fixture(autouse=True)
def _isolate_logging(monkeypatch):
    """Run each test against a pristine root logger and unset FSM_LOG_* variables."""
    monkeypatch.delenv("FSM_LOG_LEVEL", raising=False)
    monkeypatch.delenv("FSM_LOG_LEVELS", raising=False)
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    target = logging.getLogger("fsm.per_module_target")
    saved_target_level = target.level
    yield
    root.handlers[:] = saved_handlers
    root.setLevel(saved_level)
    target.setLevel(saved_target_level)
    structlog.reset_defaults()


def test_fsm_log_level_sets_the_root_level(monkeypatch, capsys):
    monkeypatch.setenv("FSM_LOG_LEVEL", "DEBUG")

    configure_logging()

    logging.getLogger("fsm.verbose").debug("wire detail")
    assert "wire detail" in capsys.readouterr().err


def test_fsm_log_levels_sets_per_module_levels(monkeypatch, capsys):
    monkeypatch.setenv("FSM_LOG_LEVELS", "fsm.per_module_target=DEBUG")

    configure_logging()

    logging.getLogger("fsm.per_module_target").debug("targeted detail")
    assert "targeted detail" in capsys.readouterr().err
