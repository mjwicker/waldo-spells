"""Logging utilities for WaldoSpells — stdlib only, no project imports.

Usage:
    from logging_utils import WaldoSpellsLogger

    logger = WaldoSpellsLogger("session")
    logger.set_file("/path/to/session.log")
    logger.info("Model loaded")
"""

import logging
from pathlib import Path
from typing import Optional


_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_LOG_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"


class WaldoSpellsLogger:
    """Thin wrapper around stdlib logging with file handler management."""

    def __init__(self, name: str, level: str = "INFO") -> None:
        self._logger = logging.getLogger(f"waldospells.{name}")
        self._logger.setLevel(getattr(logging, level.upper(), logging.INFO))
        self._logger.propagate = False
        self._file_handler: Optional[logging.FileHandler] = None
        self._formatter = logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATE_FORMAT)

    def set_file(self, filepath: str) -> None:
        """Attach or replace the file handler for this logger."""
        if self._file_handler:
            self._logger.removeHandler(self._file_handler)
            self._file_handler.close()

        try:
            Path(filepath).parent.mkdir(parents=True, exist_ok=True)
            handler = logging.FileHandler(filepath, encoding="utf-8")
            handler.setFormatter(self._formatter)
            self._logger.addHandler(handler)
            self._file_handler = handler
        except Exception:
            self._file_handler = None

    def set_level(self, level: str) -> None:
        """Set log level by name (DEBUG, INFO, WARN, ERROR)."""
        numeric = getattr(logging, level.upper(), logging.INFO)
        self._logger.setLevel(numeric)
        if self._file_handler:
            self._file_handler.setLevel(numeric)

    def debug(self, msg: str) -> None:
        self._logger.debug(msg)

    def info(self, msg: str) -> None:
        self._logger.info(msg)

    def warn(self, msg: str) -> None:
        self._logger.warning(msg)

    def error(self, msg: str, exc_info: bool = False) -> None:
        self._logger.error(msg, exc_info=exc_info)

    def close(self) -> None:
        """Close file handler and clean up."""
        if self._file_handler:
            self._logger.removeHandler(self._file_handler)
            self._file_handler.close()
            self._file_handler = None


def set_global_level(level: str) -> None:
    """Set log level on all waldospells.* loggers."""
    numeric = getattr(logging, level.upper(), logging.INFO)
    for name in list(logging.Logger.manager.loggerDict):
        if name.startswith("waldospells."):
            logging.getLogger(name).setLevel(numeric)
