"""Rotating log file in the app data folder, so problems can be reported with details."""

from __future__ import annotations

import logging
import platform
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import paths

LOGGER = "python_manager"
MAX_BYTES = 1024 * 1024
BACKUPS = 3


def log_file() -> Path:
    return paths.logs_dir() / "python-manager.log"


def setup() -> Path:
    """Attach the file handler once; later calls only return the log path."""
    path = log_file()
    logger = logging.getLogger(LOGGER)
    if not any(getattr(h, "_pm_file", False) for h in logger.handlers):
        handler = RotatingFileHandler(path, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s"))
        handler._pm_file = True
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        from .. import __version__

        logger.info("Python Manager %s on %s, Python %s", __version__, platform.platform(), sys.version.split()[0])
    return path


def get(name: str = "") -> logging.Logger:
    return logging.getLogger(f"{LOGGER}.{name}" if name else LOGGER)
