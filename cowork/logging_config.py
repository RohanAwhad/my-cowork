"""Loguru configuration — 02 §4, 07 §8.1 secret masking."""

from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path
from types import FrameType
from typing import Any

from loguru import logger

_SECRET_KEY_PATTERN = re.compile(
    r"(authorization|token|secret|api[_\-]?key|headers)",
    re.IGNORECASE,
)

_MASK = "***REDACTED***"

LOGS_DIR = Path("logs")


def _mask_secrets(record: Any) -> None:
    """Mask secret values in log record message and extra dict."""
    msg = record.get("message", "")
    if isinstance(msg, str):
        record["message"] = _SECRET_KEY_PATTERN.sub(
            lambda m: m.group(0),
            msg,
        )

    extra = record.get("extra", {})
    if isinstance(extra, dict):
        _mask_dict(extra)


def _mask_dict(d: dict[str, Any]) -> None:
    """Recursively mask values whose keys match the secret pattern."""
    for key in list(d.keys()):
        if _SECRET_KEY_PATTERN.search(key):
            d[key] = _MASK
        elif isinstance(d[key], dict):
            _mask_dict(d[key])


def _secret_filter(record: Any) -> bool:
    _mask_secrets(record)
    return True


class InterceptHandler(logging.Handler):
    """Route stdlib/uvicorn logging through loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        level: str | int
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame: FrameType | None = logging.currentframe()
        depth = 0
        while frame is not None:
            if depth > 0 and frame.f_code.co_filename != logging.__file__:
                break
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def setup_logging() -> None:
    """Configure loguru with console + file sinks, secret masking, and stdlib interception."""
    log_level = os.environ.get("LOGGING_LEVEL", "INFO").upper()

    logger.remove()

    fmt_console = (
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    )
    logger.add(
        sys.stderr,
        level=log_level,
        format=fmt_console,
        filter=_secret_filter,
        enqueue=True,
    )

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    logger.add(
        str(LOGS_DIR / "cowork.log"),
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
        rotation="10 MB",
        retention="7 days",
        filter=_secret_filter,
        enqueue=True,
    )

    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        logging.getLogger(name).handlers = [InterceptHandler()]
