"""
Nothing may restart an engine thread once the app is shutting down
(2026-10-16).

The full test sweep reproduced the on-air crash signature
(Qt6Core.dll, 0xC0000409) in test_rotation_health_screen. With Qt's
messages forced to stderr it read:

    QThread: Destroyed while thread '' is still running

Recording every QThread.start() showed the culprit: MainWindow's 150 ms
startup auto-mode timer fired AFTER close() → _cleanup_engine had
stopped everything, ran Studio Play → scheduler.start(), and the fresh
scheduler thread was later destroyed while running → qFatal → abort.

Fix: SchedulerEngine.shutdown() / RotationAIEngine.shutdown() latch the
engine so start() is a logged no-op, MainWindow's cleanup uses them, and
the deferred startup handler stands down once shutdown has begun.
"""

from __future__ import annotations

import pytest

from core.database import Database
from core.rotation_ai_engine import RotationAIEngine
from core.scheduler import SchedulerEngine


@pytest.fixture
def db():
    return Database()


def test_scheduler_start_refused_after_shutdown(qtbot, db):
    s = SchedulerEngine(db=db, tick_interval_ms=100)
    s.start()
    qtbot.waitUntil(lambda: s.tick_count >= 1, timeout=5000)
    s.shutdown()
    assert not s.is_running()
    s.start()                         # a late caller
    assert not s.is_running()
    assert s._thread is None, "a thread was created after shutdown"


def test_scheduler_shutdown_before_any_start(db):
    s = SchedulerEngine(db=db, tick_interval_ms=100)
    s.shutdown()                      # idempotent on a never-started engine
    s.start()
    assert not s.is_running()


def test_plain_stop_still_allows_restart(qtbot, db):
    """Only shutdown() latches — the AUTO pill uses stop()/start()."""
    s = SchedulerEngine(db=db, tick_interval_ms=100)
    s.start(); s.stop(); s.start()
    try:
        assert s.is_running()
        base = s.tick_count
        qtbot.waitUntil(lambda: s.tick_count > base, timeout=3000)
    finally:
        s.shutdown()


def test_rotation_engine_start_refused_after_shutdown(db):
    e = RotationAIEngine(db=db)
    e.start()
    e.shutdown()
    assert not e._running
    e.start()
    assert not e._running
    assert e._thread is None


def test_main_window_late_startup_timer_cannot_restart(qapp, db, qtbot):
    """The exact path that crashed: close() first, then the deferred
    startup auto-mode handler runs."""
    try:
        from ui.main_window import MainWindow
        mw = MainWindow(db=db)
    except Exception as exc:
        pytest.skip(f"MainWindow construction failed: {exc}")
    try:
        mw.close()
        assert mw._scheduler.is_running() is False
        mw._apply_startup_auto_mode()          # the late timer firing
        assert mw._scheduler.is_running() is False
        assert mw._scheduler._thread is None
        assert mw._rotation_engine._thread is None
    finally:
        mw.deleteLater()
