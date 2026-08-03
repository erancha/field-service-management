"""Tests for the generic structured-logging configuration.

The environment prefix is the caller's choice, so these exercise it under a prefix of their own;
that FSM processes are configured with FSM_ is asserted in tests/platform/test_logging.py.
"""
from __future__ import annotations

import logging

import pytest
import structlog

from fsm.core.logging import configure_logging

_ENV_PREFIX = "TESTAPP_"
_LEVEL_VAR = f"{_ENV_PREFIX}LOG_LEVEL"
_LEVELS_VAR = f"{_ENV_PREFIX}LOG_LEVELS"

_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access", "app.per_module_target")


def _configure() -> None:
    configure_logging(env_prefix=_ENV_PREFIX)


@pytest.fixture(autouse=True)
def _isolate_logging(monkeypatch):
    """Run each test against a pristine root logger and unset the level variables."""
    monkeypatch.delenv(_LEVEL_VAR, raising=False)
    monkeypatch.delenv(_LEVELS_VAR, raising=False)
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

    _configure()

    assert logging.getLogger().getEffectiveLevel() == logging.WARNING
    logging.getLogger("app.quiet").info("routine detail")
    assert "routine detail" not in capsys.readouterr().err


def test_env_var_overrides_default_level(monkeypatch, capsys):
    monkeypatch.setenv(_LEVEL_VAR, "debug")

    _configure()

    logging.getLogger("app.verbose").debug("wire detail")
    assert "wire detail" in capsys.readouterr().err


def test_level_variable_of_another_prefix_is_ignored(monkeypatch, capsys):
    """Processes sharing an environment steer only the variables of their own prefix."""
    monkeypatch.setenv("OTHERAPP_LOG_LEVEL", "DEBUG")

    _configure()

    logging.getLogger("app.verbose").debug("wire detail")
    assert "wire detail" not in capsys.readouterr().err


def test_per_module_levels_override_the_root_level(monkeypatch, capsys):
    monkeypatch.setenv(_LEVELS_VAR, "app.per_module_target=DEBUG")

    _configure()

    logging.getLogger("app.per_module_target").debug("targeted detail")
    logging.getLogger("app.other").debug("untargeted detail")
    err = capsys.readouterr().err
    assert "targeted detail" in err
    assert "untargeted detail" not in err


def test_stdlib_call_sites_render_with_logger_name_and_formatted_args(capsys):
    _configure()

    logging.getLogger("app.holiday_refresh").warning("Upserted %d holidays", 3)
    err = capsys.readouterr().err
    assert "Upserted 3 holidays" in err
    assert "app.holiday_refresh" in err
    assert "warning" in err.lower()


def test_structlog_loggers_carry_bound_context(capsys):
    _configure()

    structlog.get_logger("app.dispatch").bind(job_id=7).warning("dispatch failed")
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

    _configure()

    _uvicorn_access("/api/availability", 200)
    assert "/api/availability" not in capsys.readouterr().err


def test_access_logs_render_once_through_structlog_at_info(monkeypatch, capsys):
    monkeypatch.setenv(_LEVEL_VAR, "INFO")
    _install_uvicorn_access_defaults()

    _configure()

    _uvicorn_access("/api/availability", 200)
    err = capsys.readouterr().err
    assert err.count("/api/availability") == 1
    assert "uvicorn.access" in err


def test_successful_probe_requests_are_demoted_below_info(monkeypatch, capsys):
    monkeypatch.setenv(_LEVEL_VAR, "INFO")
    _install_uvicorn_access_defaults()

    _configure()

    _uvicorn_access("/health", 200)
    _uvicorn_access("/ready", 200)
    _uvicorn_access("/api/bookings", 200)
    err = capsys.readouterr().err
    assert "/health" not in err
    assert "/ready" not in err
    assert "/api/bookings" in err


def test_successful_probe_requests_appear_as_debug_at_debug_level(monkeypatch, capsys):
    monkeypatch.setenv(_LEVEL_VAR, "DEBUG")
    _install_uvicorn_access_defaults()

    _configure()

    _uvicorn_access("/health", 200)
    err = capsys.readouterr().err
    assert "/health" in err
    assert "debug" in err.lower()


def test_failing_probe_requests_keep_info_level(monkeypatch, capsys):
    monkeypatch.setenv(_LEVEL_VAR, "INFO")
    _install_uvicorn_access_defaults()

    _configure()

    _uvicorn_access("/ready", 503)
    assert "/ready" in capsys.readouterr().err


def test_reconfiguration_replaces_handlers_instead_of_stacking(capsys):
    _configure()
    _configure()

    logging.getLogger("app.repeat").warning("emitted once")
    assert capsys.readouterr().err.count("emitted once") == 1
