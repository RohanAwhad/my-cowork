"""Structured logging infrastructure for cowork.

Provides loguru-based logging with:
- JSON serializer for production (structured output)
- Human-readable colorized format for development
- Environment-based switching via ENV var
- InterceptHandler to capture stdlib/uvicorn logging
- Async-safe logging via enqueue=True
- File sink with rotation under logs/
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from loguru import logger


def _json_serializer(message: Any) -> str:
    record = message.record
    log_entry: dict[str, Any] = {
        "timestamp": record["time"].isoformat(),
        "level": record["level"].name,
        "message": record["message"],
        "source": f"{record['name']}:{record['function']}:{record['line']}",
    }
    extras = {k: v for k, v in record["extra"].items() if not k.startswith("_")}
    if extras:
        log_entry["extras"] = extras
    if record["exception"] is not None:
        log_entry["exception"] = str(record["exception"])
    return json.dumps(log_entry)


def _json_sink(message: Any) -> None:
    serialized = _json_serializer(message)
    sys.stderr.write(serialized + "\n")


_DEV_FORMAT = (
    "<green>{time:HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
    "{extra} | "
    "<level>{message}</level>"
)


class InterceptHandler(logging.Handler):
    """Routes stdlib logging into loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        level: str | int
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def setup_logging() -> None:
    log_level = os.environ.get("LOGGING_LEVEL", "INFO").upper()
    env = os.environ.get("ENV", "development").lower()
    is_production = env == "production"

    logger.remove()

    if is_production:
        logger.add(_json_sink, level=log_level, enqueue=True)
    else:
        logger.add(
            sys.stderr,
            format=_DEV_FORMAT,
            level=log_level,
            colorize=True,
            enqueue=True,
        )

    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)
    logger.add(
        str(logs_dir / "cowork.log"),
        rotation="10 MB",
        retention="7 days",
        level=log_level,
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {extra} | {message}",
        enqueue=True,
    )

    intercept_level = getattr(logging, log_level, logging.DEBUG)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        stdlib_logger = logging.getLogger(name)
        stdlib_logger.handlers = [InterceptHandler()]
        stdlib_logger.setLevel(intercept_level)
        stdlib_logger.propagate = False

    logger.info("Logging configured", env=env, level=log_level)
