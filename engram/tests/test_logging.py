"""Tests for engram logging infrastructure."""

from __future__ import annotations

import logging
import os
from unittest import mock

import pytest

from logging_config import setup_logging


class TestSetupLogging:
    def setup_method(self):
        """Reset the engram logger between tests."""
        root = logging.getLogger("engram")
        root.handlers.clear()
        root.setLevel(logging.WARNING)  # reset

    def test_setup_logging_creates_handler(self):
        logger = setup_logging("DEBUG")
        assert len(logger.handlers) == 1
        handler = logger.handlers[0]
        assert isinstance(handler, logging.StreamHandler)
        assert logger.level == logging.DEBUG

    def test_logger_names_are_namespaced(self):
        """All engram module loggers must start with 'engram.'."""
        # Import all modules to ensure their module-level loggers are created
        import storage  # noqa: F401
        import compress  # noqa: F401
        import reflection  # noqa: F401
        import indexer  # noqa: F401
        import server  # noqa: F401

        expected_modules = [
            "engram.storage",
            "engram.compression",
            "engram.reflection",
            "engram.indexer",
            "engram.server",
        ]
        manager = logging.Logger.manager
        for name in expected_modules:
            assert name in manager.loggerDict, f"Logger {name!r} not found"
            logger = logging.getLogger(name)
            assert logger.name.startswith("engram."), (
                f"Logger {logger.name!r} is not namespaced under 'engram.'"
            )

    def test_env_var_log_level(self):
        """ENGRAM_LOG_LEVEL env var should control the log level."""
        with mock.patch.dict(os.environ, {"ENGRAM_LOG_LEVEL": "DEBUG"}):
            level = os.environ.get("ENGRAM_LOG_LEVEL", "INFO")
            logger = setup_logging(level)
            assert logger.level == logging.DEBUG

        # Reset and test with WARNING
        logging.getLogger("engram").handlers.clear()
        with mock.patch.dict(os.environ, {"ENGRAM_LOG_LEVEL": "WARNING"}):
            level = os.environ.get("ENGRAM_LOG_LEVEL", "INFO")
            logger = setup_logging(level)
            assert logger.level == logging.WARNING
