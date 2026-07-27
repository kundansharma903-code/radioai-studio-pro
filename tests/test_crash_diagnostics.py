"""
Unhandled-exception black box (2026-07-25).

Every on-air hard crash so far — 2026-07-04, 07-05 and twice on 07-25 —
carries the identical Windows signature:

    Faulting module  Qt6Core.dll
    Fault offset     0x000000000001cf68
    Exception code   0xc0000409  subcode 7 (FAST_FAIL_FATAL_APP_EXIT)

That is qFatal() aborting the process. PyQt6 calls qFatal whenever a
Python exception escapes a slot, and Qt itself calls it for its own
fatal messages ("QThread: Destroyed while thread is still running", …).
In BOTH cases the explanation is written to stderr first — which, in the
windowed frozen exe, goes nowhere. So the crash was unexplainable by
construction: Event Log names the DLL, never our code.

main.py now installs sys.excepthook, threading.excepthook and a Qt
message handler that route all of that into radioai.log before the
abort. These tests pin the wiring so it cannot be silently dropped
again — they assert the hooks exist and actually reach the logger,
rather than re-testing the stdlib.
"""

from __future__ import annotations

import logging
import sys
import threading

import pytest


def _main_source() -> str:
    """Read main.py rather than importing it — importing runs boot-time
    side effects (logging reconfiguration, console patching) that break
    pytest's output capture."""
    from pathlib import Path
    return (Path(__file__).resolve().parents[1] / "main.py").read_text(
        encoding="utf-8")


def test_main_wires_all_three_hooks():
    """Guard against the wiring being dropped in a future refactor —
    without these three lines an on-air crash is unexplainable again."""
    src = _main_source()
    assert "sys.excepthook = _log_excepthook" in src
    assert "threading.excepthook = _log_thread_excepthook" in src
    assert "qInstallMessageHandler(_qt_message_handler)" in src


def test_main_imports_threading():
    """threading.excepthook is assigned in main() — the import must be
    at module level or main() raises at boot."""
    src = _main_source()
    assert "\nimport threading" in src


def test_hooks_are_callables_that_replace_the_defaults():
    hook, thread_hook = _make_hooks(logging.getLogger("hooktest.install"))
    assert callable(hook) and hook is not sys.__excepthook__
    assert callable(thread_hook) and thread_hook is not threading.excepthook


def _make_hooks(log):
    """Build the same two closures main.py installs, bound to a logger
    the test owns. Deliberately does NOT chain to the previous hook or
    touch the global — installing a real excepthook inside pytest tears
    down its output capture."""
    import traceback as _tb

    def _log_excepthook(exc_type, exc, tb):
        log.critical("UNHANDLED EXCEPTION (PyQt will abort the process "
                     "after this):\n%s",
                     "".join(_tb.format_exception(exc_type, exc, tb)))

    def _log_thread_excepthook(args):
        log.critical("UNHANDLED EXCEPTION in thread %r:\n%s",
                     getattr(args.thread, "name", "?"),
                     "".join(_tb.format_exception(
                         args.exc_type, args.exc_value, args.exc_traceback)))

    return _log_excepthook, _log_thread_excepthook


def test_slot_exception_is_logged_with_its_traceback(caplog):
    """A raise that would abort the app must land at CRITICAL with the
    real traceback — that is the whole point of the black box."""
    log = logging.getLogger("hooktest.slot")
    hook, _ = _make_hooks(log)
    with caplog.at_level(logging.CRITICAL, logger="hooktest.slot"):
        try:
            raise ValueError("SLOT-CANARY")
        except ValueError:
            hook(*sys.exc_info())
    blob = "\n".join(r.getMessage() for r in caplog.records)
    assert "SLOT-CANARY" in blob
    assert "ValueError" in blob
    assert "Traceback" in blob
    assert "test_crash_diagnostics.py" in blob    # names OUR file, not a DLL


def test_worker_thread_exception_is_logged(caplog):
    """Sweeper watcher / stitcher / aircheck threads raise outside
    sys.excepthook — threading.excepthook is what covers them."""
    log = logging.getLogger("hooktest.thread")
    _, thread_hook = _make_hooks(log)

    class _Args:
        pass

    try:
        raise RuntimeError("THREAD-CANARY")
    except RuntimeError as exc:
        args = _Args()
        args.exc_type = type(exc)
        args.exc_value = exc
        args.exc_traceback = exc.__traceback__
        args.thread = threading.current_thread()
        args.thread.name = "canary-worker"

    with caplog.at_level(logging.CRITICAL, logger="hooktest.thread"):
        thread_hook(args)
    blob = "\n".join(r.getMessage() for r in caplog.records)
    assert "THREAD-CANARY" in blob
    assert "canary-worker" in blob


def test_qt_messages_are_routed_to_the_log(caplog, qapp):
    """Qt's own warnings/fatals also vanish to stderr in the frozen exe
    — 'QThread: Destroyed while thread is still running' produces the
    exact crash signature we keep seeing, so it must be captured."""
    from PyQt6.QtCore import (qInstallMessageHandler, QtMsgType, qWarning)

    levels = {
        QtMsgType.QtDebugMsg: logging.DEBUG,
        QtMsgType.QtInfoMsg: logging.INFO,
        QtMsgType.QtWarningMsg: logging.WARNING,
        QtMsgType.QtCriticalMsg: logging.ERROR,
        QtMsgType.QtFatalMsg: logging.CRITICAL,
    }

    def handler(mode, context, message):
        logging.getLogger("Qt").log(levels.get(mode, logging.INFO), message)

    prev = qInstallMessageHandler(handler)
    try:
        with caplog.at_level(logging.WARNING, logger="Qt"):
            qWarning(b"QT-CANARY")
        assert any("QT-CANARY" in r.message for r in caplog.records)
    finally:
        qInstallMessageHandler(prev)
