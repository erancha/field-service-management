"""Structured-logging entry point every FSM process calls at start-up.

Binds the generic configuration in fsm.core.logging to this product's environment namespace, so
FSM_LOG_LEVEL and FSM_LOG_LEVELS are the variables that steer every backend process. The
model_call logger stays at INFO, so each model call's line reaches the log whatever the level.
"""
from __future__ import annotations

import logging

from fsm.assist.adapters.model_costs import MODEL_CALL_LOGGER
from fsm.core.logging import configure_logging as _configure_logging

ENV_PREFIX = "FSM_"


def configure_logging() -> None:
    """Configure logging for an FSM process. Safe to call repeatedly."""
    _configure_logging(env_prefix=ENV_PREFIX)
    logging.getLogger(MODEL_CALL_LOGGER).setLevel(logging.INFO)
