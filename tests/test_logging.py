"""Tests for logging config (setup_logging) and InterceptHandler."""
from __future__ import annotations

import json
import logging
import os
from io import StringIO
from unittest.mock import patch

from loguru import logger

from app.logging_config import InterceptHandler, setup_logging


def _capture_loguru_json() -> StringIO:
    """Add a loguru sink that writes JSON lines to a StringIO buffer."""
    buf = StringIO()

    def _sink(message: object) -> None:
        record = message.record  # type: ignore[union-attr]
        entry = {
            "level": record["level"].name,
            "message": record["message"],
        }
        extras = {k: v for k, v in record["extra"].items() if not k.startswith("_")}
        if extras:
            entry["extras"] = extras
        buf.write(json.dumps(entry) + "\n")

    logger.remove()
    logger.add(_sink, level="DEBUG", format="{message}")
    return buf


def test_setup_logging_production_adds_sinks() -> None:
    logger.remove()
    with patch.dict(os.environ, {"ENV": "production", "LOGGING_LEVEL": "DEBUG"}):
        setup_logging()
    assert len(logger._core.handlers) > 0  # type: ignore[attr-defined]
    logger.remove()


def test_setup_logging_dev_adds_sinks() -> None:
    logger.remove()
    with patch.dict(os.environ, {"ENV": "development", "LOGGING_LEVEL": "INFO"}):
        setup_logging()
    assert len(logger._core.handlers) > 0  # type: ignore[attr-defined]
    logger.remove()


def test_setup_logging_respects_logging_level() -> None:
    logger.remove()
    with patch.dict(os.environ, {"ENV": "production", "LOGGING_LEVEL": "WARNING"}):
        setup_logging()
    logger.remove()


def test_intercept_handler_forwards_info() -> None:
    buf = _capture_loguru_json()
    handler = InterceptHandler()
    stdlib_logger = logging.getLogger("test_intercept_info")
    stdlib_logger.handlers = [handler]
    stdlib_logger.setLevel(logging.DEBUG)
    stdlib_logger.propagate = False

    stdlib_logger.info("hello from stdlib")

    output = buf.getvalue()
    assert "hello from stdlib" in output
    logger.remove()


def test_intercept_handler_forwards_warning() -> None:
    buf = _capture_loguru_json()
    handler = InterceptHandler()
    stdlib_logger = logging.getLogger("test_intercept_warning")
    stdlib_logger.handlers = [handler]
    stdlib_logger.setLevel(logging.DEBUG)
    stdlib_logger.propagate = False

    stdlib_logger.warning("warn from stdlib")

    output = buf.getvalue()
    assert "warn from stdlib" in output
    lines = [json.loads(l) for l in output.strip().split("\n") if l.strip()]
    warn_lines = [l for l in lines if l["message"] == "warn from stdlib"]
    assert warn_lines[0]["level"] == "WARNING"
    logger.remove()


def test_setup_logging_lowers_stdlib_logger_level() -> None:
    with patch.dict(os.environ, {"ENV": "production", "LOGGING_LEVEL": "INFO"}):
        setup_logging()

    uvicorn_logger = logging.getLogger("uvicorn")
    assert uvicorn_logger.level <= logging.INFO
    logger.remove()
