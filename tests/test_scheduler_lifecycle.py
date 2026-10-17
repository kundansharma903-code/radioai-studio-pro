"""
SchedulerEngine lifecycle tests (Phase D3).

5 tests:
  1. start() activates is_running + emits started signal
  2. _on_tick fires at the configured interval (count ticks over time)
  3. Cross-thread signal reaches a main-thread slot via qtbot
  4. stop() is idempotent (call twice, no errors)
  5. Exception in tick → error_occurred emitted, scheduler keeps ticking

Tests use a 100ms tick_interval_ms (vs the 1000ms production default)
to keep total test runtime under ~2s.
"""

from __future__ import annotations

import time

import pytest

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from core.scheduler import SchedulerEngine
from core.database import Database


@pytest.fixture
def scheduler():
    """Fresh scheduler per test, fast-tick (100ms) for speed.
    Auto-stops on teardown."""
    s = SchedulerEngine(db=Database(), tick_interval_ms=100)
    yield s
    s.stop()


# ── Test 1: start() activates state ────────────────────────────────────

def test_start_activates_is_running(qtbot, scheduler):
    assert not scheduler.is_running()
    with qtbot.waitSignal(scheduler.started, timeout=1000):
        scheduler.start()
    assert scheduler.is_running()


# ── Test 2: tick fires at configured interval ──────────────────────────

def test_tick_fires_at_configured_interval(qtbot, scheduler):
    """100ms interval × ~500ms wait → expect ≥3 ticks (with some
    tolerance for thread startup latency)."""
    scheduler.start()
    # Wait for the FIRST tick rather than a fixed 50 ms: on a full-size
    # station DB the first tick opens the thread's connection and loads
    # the day's breaks (~120 ms), so a 50 ms warm-up measured start-up
    # cost instead of the interval and failed spuriously.
    # tick_count is bumped at the START of _on_tick, so ≥1 only means
    # the slow first tick has begun — wait for the second, which can
    # only start once the first has finished.
    qtbot.waitUntil(lambda: scheduler.tick_count >= 2, timeout=5000)
    start_count = scheduler.tick_count
    qtbot.wait(1000)
    end_count = scheduler.tick_count
    delta = end_count - start_count
    assert delta >= 5, \
        f"expected ≥5 ticks in 1000ms at 100ms interval, got {delta}"


def test_restart_after_stop_keeps_ticking(qtbot, scheduler):
    """stop() → start() must give a scheduler that TICKS again.

    Regression (2026-10-16): the engine stayed bound to its finished
    thread, moveToThread() failed on restart, and it reported
    is_running() == True with zero ticks. spot_due is emitted from the
    tick, so after AUTO off → on (or a missing-file 'Stop playback' +
    Play) ads silently stopped while music kept playing."""
    scheduler.start()
    qtbot.waitUntil(lambda: scheduler.tick_count >= 1, timeout=5000)
    scheduler.stop()
    assert not scheduler.is_running()
    # Handed back to the main thread so it can be moved again
    from PyQt6.QtCore import QCoreApplication
    from PyQt6 import sip
    assert (sip.unwrapinstance(scheduler.thread())
            == sip.unwrapinstance(QCoreApplication.instance().thread()))

    for cycle in range(2):          # survive repeated off/on
        scheduler.start()
        assert scheduler.is_running()
        base = scheduler.tick_count
        qtbot.waitUntil(lambda: scheduler.tick_count >= base + 3,
                        timeout=3000)
        scheduler.stop()


def test_restart_emits_spot_due_again(qtbot, scheduler):
    """The user-facing consequence: spots must still be dispatched
    after a restart."""
    scheduler.start()
    qtbot.waitUntil(lambda: scheduler.tick_count >= 1, timeout=5000)
    scheduler.stop()

    fired: list[int] = []
    scheduler.spot_due.connect(fired.append)
    scheduler._dispatch_due_events = (
        lambda: scheduler.spot_due.emit(777) if not fired else None)
    scheduler.start()
    qtbot.waitUntil(lambda: 777 in fired, timeout=3000)


# ── Test 3: cross-thread signal reaches main-thread slot ───────────────

def test_cross_thread_signal_marshalling(qtbot, scheduler):
    """Inject an emission of spot_due from inside _on_tick (via
    monkey-patch) and verify the main-thread waitSignal receives it.
    This proves the QueuedConnection cross-thread plumbing works."""
    scheduler.start()
    qtbot.wait(50)

    fired = False
    real_dispatch = scheduler._dispatch_due_events

    def buggy_dispatch():
        nonlocal fired
        if not fired:
            fired = True
            scheduler.spot_due.emit(42)

    scheduler._dispatch_due_events = buggy_dispatch

    with qtbot.waitSignal(scheduler.spot_due, timeout=1500) as blocker:
        pass   # waiting passively for next tick to invoke buggy_dispatch
    assert blocker.signal_triggered
    assert blocker.args == [42]

    # Restore
    scheduler._dispatch_due_events = real_dispatch


# ── Test 4: stop() is idempotent ───────────────────────────────────────

def test_stop_is_idempotent(qtbot, scheduler):
    scheduler.start()
    qtbot.wait(50)
    assert scheduler.is_running()

    scheduler.stop()
    assert not scheduler.is_running()

    # Second + third stop must be safe
    scheduler.stop()
    scheduler.stop()
    assert not scheduler.is_running()


# ── Test 5: tick exception isolated, scheduler keeps running ────────────

def test_tick_exception_does_not_kill_scheduler(qtbot, scheduler):
    """Inject a bug in _dispatch_due_events that raises every tick.
    Verify error_occurred fires AND the scheduler keeps ticking
    (tick_count keeps incrementing)."""
    scheduler.start()
    qtbot.wait(50)

    def buggy_dispatch():
        raise RuntimeError("simulated tick failure")

    scheduler._dispatch_due_events = buggy_dispatch

    with qtbot.waitSignal(scheduler.error_occurred, timeout=1500) as blocker:
        pass
    assert blocker.signal_triggered
    assert "simulated tick failure" in blocker.args[0]

    # Verify scheduler is still ticking despite the error
    pre_count = scheduler.tick_count
    qtbot.wait(300)
    post_count = scheduler.tick_count
    assert post_count > pre_count, \
        f"scheduler stopped ticking after error: {pre_count} → {post_count}"
