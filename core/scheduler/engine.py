"""
SchedulerEngine — background broadcast scheduler (Phase D3).

A QObject that lives on its own QThread. Ticks every TICK_INTERVAL_MS
(default 1000) and dispatches due events back to the Qt main thread via
pyqtSignals (queued connection — automatic across threads).

Phase D3 scope:
  - Lifecycle: start/stop/is_running with idempotent semantics
  - QThread + QTimer plumbing wired correctly (timer lives on the
    scheduler thread, not the main thread)
  - Empty _on_tick (D4 fills spot triggering, D5 fills song queue)
  - Cross-thread error isolation: tick exceptions are caught and
    surfaced via error_occurred signal; the scheduler keeps ticking

Phase D4 will:
  - Read campaign_schedule rows
  - Compute due spots (within ±30s of now)
  - Emit spot_due(campaign_id) for Studio + Spots screens to consume
  - Optionally emit break_approaching(seconds) at 30s warning

Phase D5 will:
  - React to AudioEngine.playback_ended on the deck
  - Emit song_auto_advance for Studio to load the next queue item

Threading model
---------------
The pattern is "object on a thread":
  1. SchedulerEngine constructed on main thread (parent passed in)
  2. start() detaches the parent (so we can move to a new thread),
     creates a QThread, and moveToThread(self, thread).
  3. thread.started signal triggers _on_thread_started — runs on the
     SCHEDULER thread; creates a QTimer that lives on that thread.
  4. _on_tick is invoked by the timer — runs on the scheduler thread.
     It can do DB work without blocking the UI.
  5. Public signals emit from the scheduler thread; auto-connection
     queues them onto the receiver's thread (Qt main thread for UI
     consumers).

Lifecycle contract
------------------
  Caller MUST invoke stop() before app shutdown. Idempotent — safe
  to call multiple times. MainWindow's closeEvent + aboutToQuit BOTH
  call stop() (belt-and-suspenders).

  stop() is called BEFORE AudioEngine.cleanup_all() in MainWindow —
  silence the event source first, then tear down audio.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from PyQt6.QtCore import QObject, QThread, QTimer, Qt, pyqtSignal, QMetaObject

from core.scheduler.events import EventType, ScheduledEvent

log = logging.getLogger("Scheduler")


class SchedulerEngine(QObject):
    """Background scheduler. 1Hz tick, event queue, Qt-signal-bridged
    to UI consumers."""

    # ── Public signals (cross-thread auto-marshal) ────────────────────────

    spot_due           = pyqtSignal(int)   # campaign_id
    song_auto_advance  = pyqtSignal()
    break_approaching  = pyqtSignal(int)   # seconds until break
    schedule_reloaded  = pyqtSignal()
    error_occurred     = pyqtSignal(str)
    started            = pyqtSignal()
    stopped            = pyqtSignal()

    # Lifecycle defaults
    DEFAULT_TICK_INTERVAL_MS = 1000

    def __init__(self, db, tick_interval_ms: int = DEFAULT_TICK_INTERVAL_MS,
                 parent=None):
        """db: Database singleton. Phase D4 reads campaign_schedule.

        tick_interval_ms: configurable for tests (default 1000 in
        production)."""
        super().__init__(parent)
        self._db = db
        self._tick_interval_ms = max(50, int(tick_interval_ms))
        self._thread: Optional[QThread] = None
        self._timer: Optional[QTimer] = None
        self._tick_count: int = 0
        self._running: bool = False
        self._lock = threading.Lock()

        # Phase D3+ event queue (populated by D4/D5; consumed by _on_tick)
        self._event_queue: list[ScheduledEvent] = []

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        """Spin up the QThread and kick the timer. Idempotent."""
        with self._lock:
            if self._running:
                log.debug("scheduler.start() — already running, skipping")
                return
            self._running = True

        # Detach parent before moveToThread (Qt requirement)
        self.setParent(None)

        self._thread = QThread()
        self.moveToThread(self._thread)
        self._thread.started.connect(self._on_thread_started)
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.start()
        log.info(
            f"SchedulerEngine started (tick={self._tick_interval_ms}ms)")

    def stop(self) -> None:
        """Stop the timer + tear down the thread. Idempotent. Blocks
        for up to 2s waiting for the thread to exit cleanly.

        Safe to call from any thread."""
        with self._lock:
            if not self._running:
                return
            self._running = False

        # The timer was created on the scheduler thread; ask it to stop
        # via a queued metacall so we don't touch a foreign-thread QObject.
        if self._timer is not None:
            try:
                QMetaObject.invokeMethod(
                    self._timer, "stop",
                    Qt.ConnectionType.QueuedConnection)
            except Exception as exc:
                log.debug(f"timer.stop invokeMethod failed: {exc}")
            self._timer = None

        if self._thread is not None:
            self._thread.quit()
            ok = self._thread.wait(2000)
            if not ok:
                log.warning(
                    "SchedulerEngine: thread did not exit within 2s; "
                    "calling terminate (last resort)")
                self._thread.terminate()
                self._thread.wait(500)
            self._thread = None

        log.info("SchedulerEngine stopped")

    # ── Thread plumbing (runs on scheduler thread) ───────────────────────

    def _on_thread_started(self) -> None:
        """Runs on the scheduler thread. Create the tick timer here so
        it lives on this thread."""
        self._timer = QTimer()
        self._timer.setInterval(self._tick_interval_ms)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start()
        self.started.emit()
        log.debug(f"scheduler thread {QThread.currentThread()!r} ready")

    def _on_thread_finished(self) -> None:
        """Runs on the scheduler thread (right before it exits)."""
        self.stopped.emit()

    def _on_tick(self) -> None:
        """Per-tick handler. Runs on the scheduler thread.

        Phase D3: empty body. D4 will check campaign_schedule for due
        spots; D5 will react to AudioEngine signals for queue advance.

        Wrapped in try/except so a bad tick (e.g. transient DB error)
        emits error_occurred but doesn't kill the scheduler — the next
        tick still fires."""
        self._tick_count += 1
        try:
            self._dispatch_due_events()
        except Exception as exc:
            msg = f"tick error: {type(exc).__name__}: {exc}"
            log.warning(msg)
            try:
                self.error_occurred.emit(msg)
            except Exception:
                pass

    def _dispatch_due_events(self) -> None:
        """D3: no-op. D4 will check the event queue + DB-driven schedule."""
        pass

    # ── Diagnostics ──────────────────────────────────────────────────────

    @property
    def tick_count(self) -> int:
        """How many ticks have fired since start. Useful for tests +
        debug overlays."""
        return self._tick_count
