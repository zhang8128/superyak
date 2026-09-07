"""Engram logging configuration."""

from __future__ import annotations

import logging
import sys


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configure the engram root logger with a stderr StreamHandler.

    Args:
        level: Log level name (DEBUG, INFO, WARNING, ERROR, CRITICAL).

    Returns:
        The configured root 'engram' logger.
    """
    root = logging.getLogger("engram")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Avoid adding duplicate handlers on repeated calls
    if not root.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
        )
        root.addHandler(handler)

    return root
