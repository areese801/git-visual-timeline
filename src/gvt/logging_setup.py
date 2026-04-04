"""Structured logging for gvt — writes to ~/.config/gvt/gvt.log.

gvt is a full-screen Textual TUI, so stderr logging would corrupt the display.
Instead we write to a rotating file. Level is controlled via GVT_LOG_LEVEL
(default WARNING).
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_PATH = Path.home() / ".config" / "gvt" / "gvt.log"


def get_logger(name: str = "gvt") -> logging.Logger:
    """Return a module logger with a rotating file handler attached once."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            _LOG_PATH, maxBytes=512_000, backupCount=2
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        logger.addHandler(handler)
    except OSError:
        # If we can't create the log directory, fall back to a null handler so
        # logging calls remain no-ops rather than crashing the app.
        logger.addHandler(logging.NullHandler())

    logger.setLevel(os.environ.get("GVT_LOG_LEVEL", "WARNING").upper())
    logger.propagate = False
    return logger
