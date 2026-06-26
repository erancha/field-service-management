"""Application-wide logging configuration."""
from __future__ import annotations

import logging


def configure_logging(level: str = "INFO") -> None:
    """Configure the root logger with timestamp, level, logger name, and message fields."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
