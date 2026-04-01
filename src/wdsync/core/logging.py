from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from loguru import logger

_CONCISE_FMT = "<dim>{time:YYYY-MM-DD HH:mm:ss}</dim> | <level>{level: <8}</level> | {message}\n"

_VERBOSE_FMT = (
    "<dim>{time:YYYY-MM-DD HH:mm:ss}</dim> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
    "<level>{message}</level>\n"
)


def _dynamic_format(record: Any) -> str:  # noqa: ANN401
    if record["level"].name in ("INFO", "SUCCESS"):
        return _CONCISE_FMT
    return _VERBOSE_FMT


def configure_logging(*, debug: bool = False) -> None:
    """Stage 1: console only. Call before repo discovery."""
    logger.remove()
    level = "DEBUG" if debug else os.getenv("WDSYNC_LOG_LEVEL", "INFO").upper()
    logger.add(sys.stderr, level=level, format=_dynamic_format, colorize=True)


def attach_file_logging(state_path: Path) -> None:
    """Stage 2: add file sink after repo/state directory is known."""
    log_file = state_path / "wdsync.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logger.add(
        str(log_file),
        level="DEBUG",
        rotation="5 MB",
        retention=3,
        format=_VERBOSE_FMT,
    )


log = logger
