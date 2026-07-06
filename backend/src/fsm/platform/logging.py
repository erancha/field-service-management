"""Shared structured-logging configuration for every backend process.

structlog renders structlog-native and stdlib loggers through one stderr handler, so existing
logging.getLogger call sites keep working while gaining ISO timestamps, logger names, and bound
key-value context.

Level policy: WARNING by default so routine runs stay quiet. FSM_LOG_LEVEL sets the root level
per environment; FSM_LOG_LEVELS grants per-module levels as comma-separated pairs
(e.g. "fsm.google_calendar=DEBUG,fsm.platform.sync_runner=INFO").
"""
from __future__ import annotations

import logging
import os

import structlog

_DEFAULT_LEVEL = "WARNING"

# Enrichment applied to structlog-native events and stdlib records alike before rendering.
_SHARED_PROCESSORS: list[structlog.typing.Processor] = [
    structlog.contextvars.merge_contextvars,
    structlog.stdlib.add_logger_name,
    structlog.stdlib.add_log_level,
    structlog.processors.TimeStamper(fmt="iso"),
]

# Handler installed by the most recent configure_logging call. Tracked so reconfiguration
# replaces it instead of stacking duplicates, without touching handlers owned by others
# (pytest's capture handlers in particular).
_active_handler: logging.Handler | None = None

# uvicorn installs its own handlers and a fixed INFO level on these loggers before the app
# factory runs. Left alone they bypass the root configuration entirely: access lines print in
# uvicorn's own format and ignore FSM_LOG_LEVEL. Rerouting them through the root handler makes
# every uvicorn record share one format and obey the configured level.
_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")

# Endpoints polled by orchestrator health checks. Their successful access-log lines would
# dominate INFO output across every service, so they are demoted to DEBUG; failures keep
# uvicorn's original level because a probe going bad is diagnostic signal.
_PROBE_PATHS = frozenset({"/health", "/ready"})


class _ProbeAccessDemotion(logging.Filter):
    """Demotes successful probe-endpoint records on uvicorn's access logger to DEBUG.

    uvicorn formats access lines as ('%s - "%s %s HTTP/%s" %d', addr, method, path,
    http_version, status); records of any other shape pass through untouched. Demoted
    records are then emitted only when the logger has DEBUG enabled, because uvicorn's
    own handler ignores a record's level once the logger accepted it.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if not (isinstance(args, tuple) and len(args) == 5):
            return True
        path, status = args[2], args[4]
        if not isinstance(path, str) or not isinstance(status, int):
            return True
        if path.partition("?")[0] not in _PROBE_PATHS or status >= 400:
            return True
        record.levelno = logging.DEBUG
        record.levelname = "DEBUG"
        return logging.getLogger(record.name).isEnabledFor(logging.DEBUG)


def configure_logging() -> None:
    """Route all loggers through a single structlog-formatted stderr handler.

    Reads FSM_LOG_LEVEL (default WARNING) for the root level and FSM_LOG_LEVELS for
    per-module overrides. Safe to call repeatedly.
    """
    global _active_handler

    structlog.configure(
        processors=[*_SHARED_PROCESSORS, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    handler = logging.StreamHandler()
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=_SHARED_PROCESSORS,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.dev.ConsoleRenderer(),
            ],
        )
    )

    root = logging.getLogger()
    if _active_handler is not None:
        root.removeHandler(_active_handler)
    root.addHandler(handler)
    _active_handler = handler
    root.setLevel(os.environ.get("FSM_LOG_LEVEL", _DEFAULT_LEVEL).upper())

    for spec in os.environ.get("FSM_LOG_LEVELS", "").split(","):
        name, sep, level = spec.partition("=")
        if sep and name.strip():
            logging.getLogger(name.strip()).setLevel(level.strip().upper())

    for name in _UVICORN_LOGGERS:
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.setLevel(logging.NOTSET)
        uvicorn_logger.propagate = True

    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, _ProbeAccessDemotion) for f in access_logger.filters):
        access_logger.addFilter(_ProbeAccessDemotion())
