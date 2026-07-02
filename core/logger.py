"""
RadioAI Studio Pro — Logging Setup
Rotating file log + console output.
Call setup_logging() once at startup, then get_logger() anywhere.
"""

import logging
import logging.handlers
import os


def setup_logging(debug: bool = False) -> None:
    from core.constants import LOG_PATH
    os.makedirs(LOG_PATH, exist_ok=True)

    level = logging.DEBUG if debug else logging.INFO

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-8s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Rotating file — 5 MB, keep 3 backups
    fh = logging.handlers.RotatingFileHandler(
        os.path.join(LOG_PATH, "radioai.log"),
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    fh.setFormatter(fmt)
    fh.setLevel(level)

    # Console
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    ch.setLevel(level)

    root = logging.getLogger()
    root.setLevel(level)
    # Attach by TYPE, not by "any handler present" — the frozen
    # (PyInstaller) app arrives here with a pre-existing root handler,
    # so the old `if not root.handlers:` guard silently skipped BOTH
    # handlers and the packaged exe never wrote radioai.log at all
    # (discovered 2026-07-02: zero production logs since packaging).
    have_file = any(
        isinstance(h, logging.handlers.RotatingFileHandler)
        for h in root.handlers)
    if not have_file:
        root.addHandler(fh)
    have_console = any(
        isinstance(h, logging.StreamHandler)
        and not isinstance(h, logging.handlers.RotatingFileHandler)
        for h in root.handlers)
    if not have_console:
        root.addHandler(ch)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
