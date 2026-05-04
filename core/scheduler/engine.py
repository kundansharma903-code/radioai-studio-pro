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
from datetime import datetime, date
from typing import Optional

from PyQt6.QtCore import QObject, QThread, QTimer, Qt, pyqtSignal, QMetaObject

from core.scheduler.events import EventType, ScheduledEvent

log = logging.getLogger("Scheduler")


class SchedulerEngine(QObject):
    """Background scheduler. 1Hz tick, event queue, Qt-signal-bridged
    to UI consumers."""

    # ── Public signals (cross-thread auto-marshal) ────────────────────────

    spot_due           = pyqtSignal(int)   # campaign_id (Phase D4 wired)
    song_auto_advance  = pyqtSignal()      # Phase D5 will wire
    break_approaching  = pyqtSignal(int)   # seconds — single fire at <30s
    next_break_in      = pyqtSignal(int)   # Phase D4: per-tick countdown
                                           # value -1 = no upcoming break today
    schedule_reloaded  = pyqtSignal()
    error_occurred     = pyqtSignal(str)
    started            = pyqtSignal()
    stopped            = pyqtSignal()

    # Lifecycle defaults
    DEFAULT_TICK_INTERVAL_MS = 1000

    # Phase D4 dispatch tuning
    SPOT_TOLERANCE_S = 30   # ±30s window around break_time = "due"
    BREAK_WARN_S     = 30   # break_approaching fires when ≤30s away

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

        # Phase D3+ event queue (populated by D5; consumed by _on_tick)
        self._event_queue: list[ScheduledEvent] = []

        # Phase D4: today's break schedule (cached; refreshed at day rollover)
        self._loaded_breaks: list[dict] = []
        self._loaded_date: Optional[date] = None
        # Dedupe keys: (campaign_id, break_time) for spots already fired today;
        # ('warn', campaign_id, break_time) for 30s-warning that already fired.
        self._fired_breaks: set = set()

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
        """Phase D4: real spot triggering.

        Each tick:
          1. Detect day rollover → reload schedule + clear fired-set
          2. For each break in today's schedule:
               - If within ±SPOT_TOLERANCE_S of now, emit spot_due
                 (deduped via _fired_breaks)
               - Else if within BREAK_WARN_S of now (and not yet warned),
                 emit break_approaching once
          3. Emit next_break_in(seconds) every tick — drives the
             _NextBreakCard countdown. -1 = no remaining breaks today.
        """
        now = datetime.now()
        today = now.date()

        # Day rollover — reload schedule + reset dedupe
        if self._loaded_date != today:
            try:
                self._reload_today_breaks(now)
            except Exception as exc:
                log.warning(f"break-schedule reload failed: {exc}")
                # Don't keep retrying every tick on failure — mark loaded
                # so next attempt happens at the next day rollover.
                self._loaded_date = today
                self._loaded_breaks = []
                self._fired_breaks.clear()
            else:
                self._fired_breaks.clear()
                self.schedule_reloaded.emit()
                log.info(
                    f"scheduler reloaded {len(self._loaded_breaks)} "
                    f"breaks for day {now.weekday()}")

        # Walk today's breaks; emit due / approaching; track next future
        next_break_secs = -1
        for row in self._loaded_breaks:
            break_dt = self._break_time_to_dt(row.get("break_time"), now)
            if break_dt is None:
                continue
            delta = (break_dt - now).total_seconds()

            campaign_id = int(row.get("campaign_id") or 0)
            bt_key = row.get("break_time") or ""

            # Already-fired today?
            spot_key = (campaign_id, bt_key)
            already_fired_spot = spot_key in self._fired_breaks
            warn_key = ("warn", campaign_id, bt_key)
            already_fired_warn = warn_key in self._fired_breaks

            # In the due window? (±SPOT_TOLERANCE_S around break_time)
            if (not already_fired_spot
                    and abs(delta) <= self.SPOT_TOLERANCE_S):
                self._fired_breaks.add(spot_key)
                self.spot_due.emit(campaign_id)
                log.info(
                    f"scheduler: spot_due campaign={campaign_id} "
                    f"break={bt_key} (delta={delta:+.1f}s)")

            # 30s warning — single fire when crossing the threshold from
            # outside-in. We require delta > 0 (future) AND <= BREAK_WARN_S.
            elif (not already_fired_warn
                    and 0 < delta <= self.BREAK_WARN_S):
                self._fired_breaks.add(warn_key)
                self.break_approaching.emit(int(delta))

            # Track nearest future break for the per-tick countdown
            if delta > 0 and (next_break_secs == -1
                              or delta < next_break_secs):
                next_break_secs = int(delta)

        # Per-tick countdown signal (drives _NextBreakCard)
        self.next_break_in.emit(next_break_secs)

    def _reload_today_breaks(self, now: datetime) -> None:
        """Pull today's campaign_schedule rows into the in-memory list.
        Runs on the scheduler thread (DB connection is thread-local in
        core.database, so this gets its own connection)."""
        rows = self._db.get_active_breaks_for_day(now.weekday())
        # Convert sqlite3.Row → plain dicts (Row is bound to its connection
        # and we want to read these from the scheduler thread without
        # holding the connection cursor)
        self._loaded_breaks = [dict(r) for r in rows]
        self._loaded_date = now.date()

    @staticmethod
    def _break_time_to_dt(time_str, ref_now: datetime) -> Optional[datetime]:
        """Parse 'HH:MM' or 'HH:MM:SS' into a datetime on ref_now's date.
        Returns None on bad input (logs at debug)."""
        if not time_str:
            return None
        try:
            parts = str(time_str).strip().split(":")
            h = int(parts[0])
            m = int(parts[1]) if len(parts) > 1 else 0
            s = int(parts[2]) if len(parts) > 2 else 0
            return ref_now.replace(hour=h, minute=m, second=s, microsecond=0)
        except (ValueError, IndexError):
            log.debug(f"_break_time_to_dt: unparseable {time_str!r}")
            return None

    # ── Diagnostics ──────────────────────────────────────────────────────

    @property
    def tick_count(self) -> int:
        """How many ticks have fired since start. Useful for tests +
        debug overlays."""
        return self._tick_count
