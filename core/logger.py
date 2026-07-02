"""
RadioAI Studio Pro — Logging Setup
Rotating file log + console output.
Call setup_logging() once at startup, then get_logger() anywhere.
"""

import logging
import logging.handlers
import os


def setup_logging(debug: bool = False) -> None:
    """Configure root logging. Hardened 2026-07-02: the packaged exe
    produced ZERO log output and the type-based-attach fix alone did
    not cure it, so this now (a) never lets a logging failure crash
    the app, (b) writes a bootstrap sentinel straight to the log file
    proving setup ran and the path is writable, and (c) records any
    setup failure to Logs/bootstrap_error.txt so the frozen build can
    finally tell us WHY it stays silent."""
    try:
        _setup_logging_impl(debug)
    except Exception as exc:
        try:
            import traceback
            from core.constants import LOG_PATH
            os.makedirs(LOG_PATH, exist_ok=True)
            with open(os.path.join(LOG_PATH, "bootstrap_error.txt"),
                      "a", encoding="utf-8") as f:
                f.write(f"setup_logging failed: {exc}\n")
                f.write(traceback.format_exc())
                f.write("\n")
        except Exception:
            pass


def _setup_logging_impl(debug: bool = False) -> None:
    import sys
    from datetime import datetime
    from core.constants import LOG_PATH
    os.makedirs(LOG_PATH, exist_ok=True)

    # Bootstrap sentinel — direct write, no logging machinery. If this
    # line appears in radioai.log but logger lines don't, the fault is
    # in handler wiring; if even this is missing, setup never ran or
    # the path/permissions are broken.
    logfile = os.path.join(LOG_PATH, "radioai.log")
    pre = [type(h).__name__ for h in logging.getLogger().handlers]
    with open(logfile, "a", encoding="utf-8") as f:
        f.write(
            f"{datetime.now():%Y-%m-%d %H:%M:%S} [BOOT    ] [logger] "
            f"setup_logging entered (frozen="
            f"{getattr(sys, 'frozen', False)}, debug={debug}, "
            f"pre-existing root handlers={pre})\n")

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
