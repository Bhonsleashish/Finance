"""Shared logging setup. Logs to console and to a local rotating file under
database/logs/ so nothing ever leaves the machine."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_CONFIGURED = False


def get_logger(name: str) -> logging.Logger:
    global _CONFIGURED
    if not _CONFIGURED:
        _configure_root()
        _CONFIGURED = True
    return logging.getLogger(name)


def _configure_root() -> None:
    from finance_os.config import load_settings

    settings = load_settings()
    log_dir = settings.database_file.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger("finance_os")
    root.setLevel(logging.INFO)

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    file_handler = RotatingFileHandler(log_dir / "finance_os.log", maxBytes=2_000_000, backupCount=3)
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)
