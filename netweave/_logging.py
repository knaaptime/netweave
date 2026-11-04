"""Internal logging utilities for netweave.

Provides two levels of logging:
- ``status()``: concise user-facing console messages (always active).
- ``_log()``: verbose structured logging, only active when ``settings.debug=True``.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from netweave.config import settings

# ---------------------------------------------------------------------------
# Internal: verbose structured logger (debug mode only)
# ---------------------------------------------------------------------------


def _get_logger(name: str = "netweave") -> logging.Logger | None:
    """Return the netweave logger, creating handlers if necessary.

    Returns None if debug mode is disabled.
    """
    if not settings.debug:
        return None

    logger = logging.getLogger(name)
    if logger.hasHandlers():
        return logger

    logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))

    formatter = logging.Formatter(
        "%(asctime)s | %(name)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if settings.log_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    log_path = Path(settings.log_folder) / settings.log_file
    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


def _log(message: str, level: int = logging.INFO) -> None:
    """Log a verbose structured message (debug mode only).

    When ``settings.debug`` is False, this is a no-op.

    Parameters
    ----------
    message : str
        Message to log.
    level : int, optional
        Logging level (default ``logging.INFO``).
    """
    logger = _get_logger()
    if logger is not None:
        logger.log(level, message)


# ---------------------------------------------------------------------------
# Public: concise user-facing status messages
# ---------------------------------------------------------------------------


def status(message: str) -> None:
    """Print a concise status message to the console.

    This is the primary way to communicate progress to users. It prints
    a simple message without timestamps or log levels. Inside a ``tqdm``
    loop, use ``tqdm.write(message)`` instead to avoid breaking the bar.

    Parameters
    ----------
    message : str
        Status message to display.
    """
    print(message)
