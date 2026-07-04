"""Tests for the shared structured-logging configuration used by every backend process."""
from __future__ import annotations

import logging

import pytest
import structlog

from fsm.platform.logging import configure_logging


_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access", "fsm.per_module_target")


@pytest.fixture(autouse=True)
def _isolate_logging(monkeypatch):
    """Run each test against a pristine root logger and unset FSM_LOG_* variables."""
    monkeypatch.delenv("FSM_LOG_LEVEL", raising=False)
    monkeypatch.delenv("FSM_LOG_LEVELS", raising=False)
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    saved = {
        name: (lg.handlers[:], lg.filters[:], lg.level, lg.propagate)
        for name in _UVICORN_LOGGERS
        for lg in [logging.getLogger(name)]
    }
    yield
    root.handlers[:] = saved_handlers
    root.setLevel(saved_level)
    for name, (handlers, filters, level, propagate) in saved.items():
        lg = logging.getLogger(name)
        lg.handlers[:] = handlers
        lg.filters[:] = filters
        lg.setLevel(level)
        lg.propagate = propagate
    structlog.reset_defaults()


def _install_uvicorn_access_defaults():
    """Reproduce uvicorn's own logging setup: an INFO access logger with its own non-propagating
    handler, installed before the app factory calls configure_logging."""
    access = logging.getLogger("uvicorn.access")
    access.handlers[:] = [logging.StreamHandler()]
    access.setLevel(logging.INFO)
    access.propagate = False


def test_default_level_is_warning(capsys):
    logging.getLogger().setLevel(logging.INFO)

    configure_logging()

    assert logging.getLogger().getEffectiveLevel() == logging.WARNING
    logging.getLogger("fsm.quiet").info("routine detail")
    assert "routine detail" not in capsys.readouterr().err


def test_env_var_overrides_default_level(monkeypatch, capsys):
    monkeypatch.setenv("FSM_LOG_LEVEL", "debug")

    configure_logging()

    logging.getLogger("fsm.verbose").debug("wire detail")
    assert "wire detail" in capsys.readouterr().err


def test_per_module_levels_override_the_root_level(monkeypatch, capsys):
    monkeypatch.setenv("FSM_LOG_LEVELS", "fsm.per_module_target=DEBUG")

    configure_logging()

    logging.getLogger("fsm.per_module_target").debug("targeted detail")
    logging.getLogger("fsm.other").debug("untargeted detail")
    err = capsys.readouterr().err
    assert "targeted detail" in err
    assert "untargeted detail" not in err


def test_stdlib_call_sites_render_with_logger_name_and_formatted_args(capsys):
    configure_logging()

    logging.getLogger("fsm.platform.holiday_refresh").warning("Upserted %d holidays", 3)
    err = capsys.readouterr().err
    assert "Upserted 3 holidays" in err
    assert "fsm.platform.holiday_refresh" in err
    assert "warning" in err.lower()


def test_structlog_loggers_carry_bound_context(capsys):
    configure_logging()

    structlog.get_logger("fsm.dispatch").bind(job_id=7).warning("dispatch failed")
    err = capsys.readouterr().err
    assert "dispatch failed" in err
    assert "job_id" in err
    assert "7" in err


def _uvicorn_access(path: str, status: int) -> None:
    """Emit a record shaped exactly like uvicorn's access log for the given request."""
    logging.getLogger("uvicorn.access").info(
        '%s - "%s %s HTTP/%s" %d', "127.0.0.1:1000", "GET", path, "1.1", status
    )


def test_access_logs_obey_the_root_level_despite_uvicorn_defaults(capsys):
    _install_uvicorn_access_defaults()

    configure_logging()

    _uvicorn_access("/api/availability", 200)
    assert "/api/availability" not in capsys.readouterr().err


def test_access_logs_render_once_through_structlog_at_info(monkeypatch, capsys):
    monkeypatch.setenv("FSM_LOG_LEVEL", "INFO")
    _install_uvicorn_access_defaults()

    configure_logging()

    _uvicorn_access("/api/availability", 200)
    err = capsys.readouterr().err
    assert err.count("/api/availability") == 1
    assert "uvicorn.access" in err


def test_successful_probe_requests_are_demoted_below_info(monkeypatch, capsys):
    monkeypatch.setenv("FSM_LOG_LEVEL", "INFO")
    _install_uvicorn_access_defaults()

    configure_logging()

    _uvicorn_access("/health", 200)
    _uvicorn_access("/ready", 200)
    _uvicorn_access("/api/bookings", 200)
    err = capsys.readouterr().err
    assert "/health" not in err
    assert "/ready" not in err
    assert "/api/bookings" in err


def test_successful_probe_requests_appear_as_debug_at_debug_level(monkeypatch, capsys):
    monkeypatch.setenv("FSM_LOG_LEVEL", "DEBUG")
    _install_uvicorn_access_defaults()

    configure_logging()

    _uvicorn_access("/health", 200)
    err = capsys.readouterr().err
    assert "/health" in err
    assert "debug" in err.lower()


def test_failing_probe_requests_keep_info_level(monkeypatch, capsys):
    monkeypatch.setenv("FSM_LOG_LEVEL", "INFO")
    _install_uvicorn_access_defaults()

    configure_logging()

    _uvicorn_access("/ready", 503)
    assert "/ready" in capsys.readouterr().err


def test_reconfiguration_replaces_handlers_instead_of_stacking(capsys):
    configure_logging()
    configure_logging()

    logging.getLogger("fsm.repeat").warning("emitted once")
    assert capsys.readouterr().err.count("emitted once") == 1
