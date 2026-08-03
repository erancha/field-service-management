"""Structured-logging entry point every FSM process calls at start-up.

Binds the generic configuration in fsm.core.logging to this product's environment namespace, so
FSM_LOG_LEVEL and FSM_LOG_LEVELS are the variables that steer every backend process.
"""
from __future__ import annotations

from fsm.core.logging import configure_logging as _configure_logging

ENV_PREFIX = "FSM_"


def configure_logging() -> None:
    """Configure logging for an FSM process. Safe to call repeatedly."""
    _configure_logging(env_prefix=ENV_PREFIX)
