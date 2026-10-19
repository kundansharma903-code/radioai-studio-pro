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
import os
import threading
import time
from datetime import datetime, date, timedelta
from typing import Optional

from PyQt6.QtCore import (
    QObject, QThread, QTimer, Qt, pyqtSignal, QMetaObject, QCoreApplication,
)
from PyQt6 import sip

from core.scheduler.events import EventType, ScheduledEvent

log = logging.getLogger("Scheduler")

# QThreads that refused to stop even after terminate(). They are kept
# alive here for the rest of the process: dropping the last reference
# to a RUNNING QThread makes Qt call qFatal("QThread: Destroyed while
# thread is still running"), which Windows reports as Qt6Core.dll
# 0xC0000409 — the on-air crash signature.
_PARKED_THREADS: list = []


def _same_thread(a, b) -> bool:
    try:
        return sip.unwrapinstance(a) == sip.unwrapinstance(b)
    except Exception:
        return a is b



def _file_exists(row) -> bool:
    """True when ``row['file_path']`` is set and exists on disk."""
    import os
    try:
        fp = row["file_path"]
    except (IndexError, KeyError, TypeError):
        return False
    return bool(fp) and os.path.exists(fp)

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
    # Hour-boundary detection (additive — does not affect dispatch logic).
    # Emits (clock_id, name) when the active clock for current
    # (day_of_week, hour) changes. clock_id = -1, name = "" when no
    # clock is assigned to the current cell. Deduped — re-emits only
    # when the resolved clock genuinely changes from the previous tick.
    active_clock_changed = pyqtSignal(int, str)
    # Phase 2 (2026-05-17) — single canonical "queue changed" signal.
    # Fires whenever the dispatch queue / preview SHOULD be refreshed by
    # UI consumers (Up Coming panel, NEXT chip, RDS). Sources:
    #   • pick_next_item advanced the cursor (a real dispatch happened)
    #   • schedule_reloaded (day rollover or force-reload)
    #   • active_clock_changed (hour-boundary, different clock now active)
    # Studio also re-emits its own queue_changed proxy for in-Studio
    # mutations (pending spot/SOTG appends, drains, drag/drop). UI panels
    # subscribe to ONE signal source instead of scattered hooks. Replaces
    # the manual `_load_upcoming_queue()` calls peppered through Studio
    # — those calls remain as a defence-in-depth backstop but the signal
    # path is now the primary refresh trigger.
    queue_changed      = pyqtSignal()

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
        # Set by shutdown(): once the app is tearing down, NOTHING may
        # start the engine again (see shutdown()).
        self._shut_down: bool = False

        # Phase D3+ event queue (populated by D5; consumed by _on_tick)
        self._event_queue: list[ScheduledEvent] = []

        # Phase D4: today's break schedule (cached; refreshed at day rollover)
        self._loaded_breaks: list[dict] = []
        self._loaded_date: Optional[date] = None
        # Dedupe keys: (campaign_id, break_time) for spots already fired today;
        # ('warn', campaign_id, break_time) for 30s-warning that already fired.
        self._fired_breaks: set = set()
        # Day whose already-aired breaks were last rebuilt from
        # broadcast_log into _fired_breaks (QA ⚠23). None = never: the
        # set is in-memory only, so without this a restart re-aired
        # every break earlier in the hour that had already gone out.
        self._fired_seeded_date: Optional[date] = None
        # Guards every add/clear/copy of _fired_breaks — the scheduler
        # thread adds keys while peek_next (main thread) snapshots it.
        self._fired_lock = threading.Lock()
        # Per-thread simulation set used by _pick_break while peek_next
        # runs, so a preview never touches (or replaces) the real set.
        self._peek_local = threading.local()
        # Live reload (2026-10-17): set by reload_breaks() from any
        # thread; the next tick reloads in place (keeps _fired_breaks).
        self._breaks_dirty: bool = False
        # monotonic() deadline for the next retry after a failed load
        # (None = no retry pending).
        self._breaks_retry_at: Optional[float] = None

        # Phase F2: clock-slot cursor for pick_next_song. Reset on hour
        # rollover so each hour starts at slot 0.
        self._clock_slot_cursor: int = 0
        self._active_hour_key: Optional[tuple[int, int]] = None
        # Clock the cursor indexes into — reset the cursor when the
        # resolved clock changes (force override / grid edit).
        self._cursor_clock_id: Optional[int] = None

        # Active-clock tracking (Studio header indicator).
        # `_active_clock_id is None` means "no tick has resolved yet" —
        # current_active_clock() returns (None, "") for that pre-tick
        # state. After the first tick a real id (or -1 for unassigned)
        # is set, and active_clock_changed fires only on transitions.
        self._active_clock_id: Optional[int] = None
        self._active_clock_name: str = ""

        # Phase E5: Rotation AI engine handle. Set via
        # set_rotation_engine() from MainWindow at boot. When non-None
        # AND today's plan is approved/auto_applied, _pick_song
        # consults rotation_engine.pick_song_for_clock() BEFORE
        # falling back to native random + separation logic (operator's
        # Q4 = (b) safe fallback when AI off or rejected).
        self._rotation_engine = None
        # Per-pick context — set at the top of pick_next_item so
        # _pick_song can read them without changing the picker signature
        self._current_pick_clock_id: Optional[int] = None
        self._current_pick_hour: Optional[int] = None

        # Rotation-plan decision memo (BUG-2/BUG-3 fix). peek_next
        # simulates 5 picks per queue refresh on the 1 Hz scheduler
        # thread — the approved-decision lookup must not re-query the
        # DB each time. Keyed on (date, clock_id, hour); refetched only
        # when the key changes (hour rollover / clock change / new day).
        self._rot_dec_cache_key: Optional[tuple] = None
        self._rot_dec_cache: dict = {
            "active": False, "rest_ids": set(), "picks": []}
        self._rot_dec_cache_at: float = 0.0   # monotonic ts of last fetch
        # Set when a cache refresh changes the result; _on_tick emits
        # queue_changed (never from inside a peek simulation).
        self._queue_dirty: bool = False

        # Category air-time tags (core.category_air_time). Read with a
        # 60 s TTL — peek_next simulates 5 picks per refresh — so a tag
        # saved in Edit Categories goes live within a minute.
        self._air_time_parts: list = []
        self._air_time_playable: set = set()   # tagged cats with songs
        self._air_time_names: dict = {}
        self._air_time_at: float = -1e9
        self._air_time_logged: set = set()

    def set_rotation_engine(self, engine) -> None:
        """Install a RotationAIEngine handle. Pass None to detach
        (reverts to native random + separation pick)."""
        self._rotation_engine = engine

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        """Spin up the QThread and kick the timer. Idempotent.

        Restartable (2026-10-16). Before this, stop() left the engine
        bound to its dead thread, so on the next start() moveToThread()
        failed with "Current thread is not the object's thread" and the
        engine reported running=True while its timer never fired. Studio
        still pulled songs via pick_next_item(), so playout SOUNDED fine
        — but spot_due comes from the tick, so ads silently stopped
        after AUTO off→on or a missing-file "Stop playback" + Play.
        _on_thread_finished now hands the engine back to the main thread.
        """
        with self._lock:
            if self._shut_down:
                log.info("scheduler.start() ignored — engine is shut down")
                return
            if self._running:
                log.debug("scheduler.start() — already running, skipping")
                return
            self._running = True

        # Only an object that lives on THIS thread can be moved. If the
        # previous thread never handed us back (it hung and was parked),
        # starting would produce a scheduler that claims to run but never
        # ticks — refuse loudly so Studio falls back visibly instead.
        if not _same_thread(self.thread(), QThread.currentThread()):
            with self._lock:
                self._running = False
            msg = ("SchedulerEngine.start() refused — engine is still "
                   "bound to a previous thread that did not shut down")
            log.error(msg)
            try:
                self.error_occurred.emit(msg)
            except Exception:
                pass
            return

        # Detach parent before moveToThread (Qt requirement)
        self.setParent(None)

        self._thread = QThread()
        self.moveToThread(self._thread)
        self._thread.started.connect(self._on_thread_started)
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.start()
        log.info(
            f"SchedulerEngine started (tick={self._tick_interval_ms}ms)")

    def shutdown(self) -> None:
        """Final stop for app exit: stop, and refuse every later start().

        Found 2026-10-16 with the exact on-air crash signature: the
        150 ms startup auto-mode timer (MainWindow._apply_startup_auto_mode
        → Studio Play → scheduler.start()) can fire AFTER
        MainWindow._cleanup_engine has stopped everything. That started
        a fresh scheduler thread, and when its owner was garbage-collected
        the running QThread was destroyed → qFatal("QThread: Destroyed
        while thread is still running") → Qt6Core.dll 0xC0000409.
        Any late caller (timer, showEvent auto-arm, AUTO pill) is now a
        logged no-op instead."""
        with self._lock:
            self._shut_down = True
        self.stop()

    def stop(self) -> None:
        """Stop the timer + tear down the thread. Idempotent. Blocks
        for up to 2s waiting for the thread to exit cleanly.

        Safe to call from any thread."""
        with self._lock:
            if not self._running:
                return
            self._running = False

        # The tick timer lives on the scheduler thread and is torn down
        # THERE, in _on_thread_finished. It used to be dropped from this
        # (main) thread with `self._timer = None`, which deleted a QObject
        # owned by another, still-running thread.
        thread = self._thread
        if thread is not None:
            thread.quit()
            ok = thread.wait(2000)
            if not ok:
                log.warning(
                    "SchedulerEngine: thread did not exit within 2s; "
                    "calling terminate (last resort)")
                thread.terminate()
                ok = thread.wait(2000)
            if not ok or thread.isRunning():
                # Never drop the last reference to a running QThread —
                # that is qFatal() → Qt6Core 0xC0000409 on Windows.
                _PARKED_THREADS.append(thread)
                log.error(
                    "SchedulerEngine: thread still running after "
                    "terminate — parked to avoid a hard crash")
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
        """Runs on the scheduler thread (right before it exits).

        Tears the tick timer down on its OWN thread, then hands the
        engine back to the main thread. moveToThread() may only be
        called from the object's current thread, so this is the one
        place it can happen — without it the next start() cannot move
        the engine onto a fresh QThread (see start())."""
        t, self._timer = self._timer, None
        if t is not None:
            try:
                t.stop()
            except Exception as exc:
                log.debug(f"timer stop on finish: {exc}")
            del t                       # deleted here, on its own thread
        try:
            app = QCoreApplication.instance()
            if app is not None:
                self.moveToThread(app.thread())
        except Exception as exc:
            log.warning(f"SchedulerEngine: hand-back to main failed: {exc}")
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
        # Active-clock tracking is its own try/except so a DB blip on
        # this path can never freeze the dispatch tick (which lives in
        # _dispatch_due_events above). Broadcast safety: keep the
        # 1Hz heartbeat alive at all costs.
        self._check_active_clock_change()
        # Deferred queue_changed from a cache refresh that changed what
        # slots may air (plan approval, air-time edit, invalidation).
        # Raised inside picks — possibly during a peek simulation — so
        # it is emitted here, never inside the suppressed window.
        if self._queue_dirty and not self._suppress_queue_emit:
            self._queue_dirty = False
            try:
                self.queue_changed.emit()
            except Exception:
                pass

    # ── Active-clock tracking (Studio header indicator) ───────────────────

    def _check_active_clock_change(self) -> None:
        """Resolve the clock assigned to the current ``(weekday, hour)``
        cell and fire ``active_clock_changed`` only when it differs from
        the value cached on the previous tick. Hour-boundary detection
        works automatically — at minute 00 of a new hour the resolved
        clock changes (to either a different clock or to the no-clock
        sentinel), and the dedupe lets it fire once per transition.

        Day rollover handled implicitly: ``datetime.now().weekday()``
        returns 0=Mon..6=Sun, so a Sunday→Monday boundary at midnight
        picks Monday's cell on the very first post-rollover tick.

        Wrapped in try/except — a transient DB error must NOT propagate
        and freeze ``_on_tick``. Previous state is preserved on failure
        so the indicator displays the last known clock until the next
        successful resolve."""
        try:
            # Shared resolver (force override → grid) — the indicator
            # must name the clock dispatch actually plays.
            from core.clock_resolver import resolve_clock
            res = resolve_clock(self._db, datetime.now())
            if res is None:
                new_id = -1
                new_name = ""
            else:
                new_id = int(res["id"])
                new_name = res["name"]
        except Exception as exc:
            log.warning(f"active-clock check failed: "
                        f"{type(exc).__name__}: {exc}")
            return

        # Dedupe — only emit on transitions. Pre-tick state is None so
        # the first successful resolve always emits.
        if (self._active_clock_id == new_id
                and self._active_clock_name == new_name):
            return
        self._active_clock_id = new_id
        self._active_clock_name = new_name
        try:
            self.active_clock_changed.emit(int(new_id), new_name)
        except Exception:
            # Cross-thread emit failures are non-fatal — the next
            # tick (or transition) will retry.
            pass
        # Phase 2 (2026-05-17) — clock change → different slot list
        # applies; peek_next will return different items. Trigger
        # queue refresh so the Up Coming panel + NEXT chip re-render.
        try:
            self.queue_changed.emit()
        except Exception:
            pass

    def current_active_clock(self) -> tuple[Optional[int], str]:
        """Read-only snapshot of the currently-resolved active clock.

        Returns:
            (clock_id, name) where ``clock_id`` is -1 when no clock is
            assigned to the current cell, or ``None`` when no tick has
            yet resolved (pre-start state). ``name`` is "" when the
            clock_id has no readable name OR no clock is assigned.

        Useful for the Studio header to seed its indicator at
        construction without waiting for the first tick."""
        return self._active_clock_id, self._active_clock_name

    # ════════════════════════════════════════════════════════════════════
    # CRITICAL INVARIANT — _suppress_queue_emit gate (2026-05-17 lock)
    # ════════════════════════════════════════════════════════════════════
    # When peek_next runs simulated dispatches, it suppresses
    # queue_changed emissions to prevent a signal storm.
    #
    # Without this gate: every peek_next(5) would emit queue_changed
    # 5 times -> Studio's _on_scheduler_queue_changed handler re-calls
    # peek_next -> 5 more emits -> exponential cascade -> Qt event
    # queue floods -> UI freezes ("NEXT chip frozen" symptom observed
    # 2026-05-17 and root-caused).
    #
    # DO NOT REMOVE this flag or the gate check in pick_next_item.
    # If you need to add a new caller that walks the dispatch loop
    # non-destructively (like peek_next does), it MUST also set this
    # flag True during its simulation and restore False after.
    #
    # The cursor IS still advanced inside the simulated loop and
    # restored in peek_next's finally block — only the public-signal
    # side effect is gated by this flag.
    # ════════════════════════════════════════════════════════════════════
    _suppress_queue_emit: bool = False

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
                # Don't hammer the DB every tick, but don't give up for
                # the whole day either — retry every BREAK_RETRY_S.
                self._loaded_date = today
                self._loaded_breaks = []
                with self._fired_lock:
                    self._fired_breaks.clear()
                self._seed_fired_from_log(now, force=True)
                self._note_break_load_failure(exc)
            else:
                self._breaks_retry_at = None
                self._breaks_dirty = False
                with self._fired_lock:
                    self._fired_breaks.clear()
                # The clear is for a NEW day; on the first tick after a
                # restart it would forget breaks that already aired today
                # — rebuild them from broadcast_log (QA ⚠23).
                self._seed_fired_from_log(now, force=True)
                # New day → yesterday's rotation-plan decisions are
                # stale; force a refetch on the next pick.
                self._rot_dec_cache_key = None
                # Category Auto-Grid: reconcile the weekly grid with
                # the category daypart tags BEFORE anything reads it
                # today (plan compute, clock resolution). Guarded —
                # a builder failure must never kill the tick, and the
                # weekly grid keeps working on last build regardless.
                try:
                    from core.auto_grid_builder import build_grid
                    res = build_grid(self._db)
                    if res.get("placed") or res.get("cleared"):
                        log.info(f"day-rollover auto-grid: {res}")
                except Exception as exc:
                    log.warning(f"auto-grid on rollover failed: {exc}")
                self.schedule_reloaded.emit()
                # Phase 2 — reload changes the whole event picture;
                # surface as queue_changed for UI consumers.
                try:
                    self.queue_changed.emit()
                except Exception:
                    pass
                log.info(
                    f"scheduler reloaded {len(self._loaded_breaks)} "
                    f"breaks for day {now.weekday()}")
        elif self._breaks_dirty or (
                self._breaks_retry_at is not None
                and time.monotonic() >= self._breaks_retry_at):
            # Live reload (campaign edited / failed-load retry): reload
            # IN PLACE — _fired_breaks is kept so already-aired breaks
            # never re-fire.
            self._breaks_dirty = False
            try:
                self._reload_today_breaks(now)
            except Exception as exc:
                self._note_break_load_failure(exc)
            else:
                self._breaks_retry_at = None
                # A campaign edited/added today may already have aired.
                self._seed_fired_from_log(now, force=True)
                log.info(
                    f"scheduler live-reloaded {len(self._loaded_breaks)} "
                    f"breaks (fired set kept)")
                try:
                    self.queue_changed.emit()
                except Exception:
                    pass

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
                with self._fired_lock:
                    self._fired_breaks.add(spot_key)
                self.spot_due.emit(campaign_id)
                log.info(
                    f"scheduler: spot_due campaign={campaign_id} "
                    f"break={bt_key} (delta={delta:+.1f}s)")

            # 30s warning — single fire when crossing the threshold from
            # outside-in. We require delta > 0 (future) AND <= BREAK_WARN_S.
            elif (not already_fired_warn
                    and 0 < delta <= self.BREAK_WARN_S):
                with self._fired_lock:
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
        self._loaded_breaks = [{k: r[k] for k in r.keys()} for r in rows]
        self._loaded_date = now.date()

    # Failed break-schedule loads are retried this often (seconds).
    BREAK_RETRY_S = 60

    def reload_breaks(self) -> None:
        """Public, thread-safe: mark today's break schedule dirty. The
        next scheduler tick reloads it IN PLACE (``_fired_breaks`` is
        kept, so breaks that already aired never re-fire) and emits
        ``queue_changed``. Call after any campaign / schedule edit."""
        self._breaks_dirty = True

    def _note_break_load_failure(self, exc) -> None:
        """Schedule a retry in BREAK_RETRY_S and tell the operator."""
        self._breaks_retry_at = time.monotonic() + self.BREAK_RETRY_S
        msg = (f"Could not load today's commercial breaks ({exc}) — "
               f"spots will NOT air until this succeeds; retrying in "
               f"{self.BREAK_RETRY_S}s.")
        log.warning(msg)
        try:
            self.error_occurred.emit(msg)
        except Exception:
            pass

    def _fired_snapshot(self) -> set:
        with self._fired_lock:
            return set(self._fired_breaks)

    def _seed_fired_from_log(self, now: datetime,
                             force: bool = False) -> None:
        """Rebuild today's "already aired" breaks from broadcast_log
        into _fired_breaks (QA ⚠23, 2026-10-18).

        _fired_breaks lives only in memory. After a restart, neither
        _pick_break (any break earlier this hour is "due") nor the
        spot_due tick knew what had aired, so a paid spot that went out
        at 09:15 could air again at 09:40.

        Each logged spot airing is matched to ONE break of its campaign:
        the earliest unmatched break with break_time - SPOT_TOLERANCE_S
        <= played_at, scanning breaks in time order. So a spot held by
        Break Policy and aired late still counts for its own break and
        not for the campaign's next one, and a held spot that has NOT
        aired yet has no log row and stays unfired. Future breaks are
        never marked. Idempotent per day unless ``force``. Times are
        LOCAL 'YYYY-MM-DD HH:MM:SS', the format played_at is stored in."""
        today = now.date()
        if not force and self._fired_seeded_date == today:
            return
        self._fired_seeded_date = today
        tol = timedelta(seconds=self.SPOT_TOLERANCE_S)
        midnight = datetime.combine(today, datetime.min.time())
        try:
            breaks = list(self._db.get_active_breaks_for_day(
                int(now.weekday())) or [])
            plays = self._db.get_spot_plays_between(
                (midnight - tol).strftime("%Y-%m-%d %H:%M:%S"),
                (midnight + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"))
        except Exception as exc:
            # Fake / older DBs without the helper, or a transient error:
            # leave the set as it is (the previous behaviour).
            log.debug(f"seed fired breaks from log skipped: {exc}")
            return
        airings: dict = {}
        try:
            for cid, played_at in plays:
                airings.setdefault(int(cid), []).append(str(played_at))
        except (TypeError, ValueError) as exc:
            log.debug(f"seed fired breaks: unusable play rows: {exc}")
            return
        timed = []
        for br in breaks:
            try:
                raw = str(br["break_time"] or "")
                cid = int(br["campaign_id"])
            except (KeyError, IndexError, TypeError, ValueError):
                continue
            bdt = self._break_time_to_dt(raw.strip(), now)
            if bdt is None or bdt > now + tol:
                continue                     # not due yet → can't have aired
            timed.append((bdt, cid, raw))
        keys: set = set()
        matched = 0
        for bdt, cid, raw in sorted(timed):
            pending = airings.get(cid) or []
            lo = (bdt - tol).strftime("%Y-%m-%d %H:%M:%S")
            for i, played_at in enumerate(pending):
                if played_at >= lo:
                    del pending[i]           # one airing → one break
                    matched += 1
                    for bt in {raw, raw.strip()}:
                        keys.add((cid, bt))
                        keys.add(("warn", cid, bt))
                    break
        if keys:
            with self._fired_lock:
                self._fired_breaks |= keys
            log.info(f"scheduler: {matched} break(s) already aired today "
                     f"restored from broadcast_log")

    def next_break_info(self, now: Optional[datetime] = None) -> Optional[dict]:
        """The next not-yet-fired break (all campaigns sharing its
        break_time) from the loaded — i.e. date-filtered — schedule.
        Returns {break_time, break_dt, seconds, campaign_ids,
        campaign_names} or None. Read-only; safe from any thread."""
        now = now or datetime.now()
        fired = self._fired_snapshot()
        best_dt, groups = None, {}
        for row in list(self._loaded_breaks):
            bt = row.get("break_time") or ""
            bdt = self._break_time_to_dt(bt, now)
            if bdt is None:
                continue
            cid = int(row.get("campaign_id") or 0)
            if (cid, bt) in fired:
                continue
            if (bdt - now).total_seconds() < -self.SPOT_TOLERANCE_S:
                continue
            groups.setdefault(bdt, []).append(row)
            if best_dt is None or bdt < best_dt:
                best_dt = bdt
        if best_dt is None:
            return None
        rows = groups[best_dt]
        return {
            "break_time": rows[0].get("break_time") or "",
            "break_dt": best_dt,
            "seconds": int((best_dt - now).total_seconds()),
            "campaign_ids": [int(r.get("campaign_id") or 0) for r in rows],
            "campaign_names": [r.get("campaign_name") or "Spot"
                               for r in rows],
        }

    def upcoming_breaks(self, within_s: int,
                        now: Optional[datetime] = None) -> list[dict]:
        """Unfired loaded breaks due within ``within_s`` seconds (and not
        older than SPOT_TOLERANCE_S). Same filtered source as dispatch."""
        now = now or datetime.now()
        fired = self._fired_snapshot()
        out = []
        for row in list(self._loaded_breaks):
            bt = row.get("break_time") or ""
            bdt = self._break_time_to_dt(bt, now)
            if bdt is None:
                continue
            if (int(row.get("campaign_id") or 0), bt) in fired:
                continue
            delta = (bdt - now).total_seconds()
            if -self.SPOT_TOLERANCE_S <= delta <= within_s:
                out.append(dict(row))
        return out

    def skip_next_break(self, now: Optional[datetime] = None) -> Optional[dict]:
        """Mark every campaign of the next unfired break as fired so it
        will not dispatch. Returns the skipped break info (or None)."""
        info = self.next_break_info(now)
        if not info:
            return None
        with self._fired_lock:
            for cid in info["campaign_ids"]:
                self._fired_breaks.add((cid, info["break_time"]))
                self._fired_breaks.add(("warn", cid, info["break_time"]))
        log.info(f"scheduler: operator SKIPPED break {info['break_time']} "
                 f"campaigns={info['campaign_ids']}")
        return info

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

    # ── Phase F-Final: clock-driven rotation engine (full Jazler set) ────

    # Default separation windows. Configurable via scheduling_rules table
    # in a future polish pass — for now hard-coded sane defaults.
    SEPARATION_SAME_ARTIST_MIN = 60   # no same artist within 60 min
    SEPARATION_SAME_SONG_MIN   = 240  # no same song    within 4 hours

    def pick_next_item(self, now: Optional[datetime] = None) -> Optional[dict]:
        """Phase F-Final — full Jazler-equivalent clock dispatcher.

        Resolves the active clock for current (day_of_week, hour) via
        force_clocks override → auto_schedule fallback. Walks slots from
        the cursor position; dispatches by slot_type to the matching
        picker. Returns the first non-None pick.

        Returns:
            {item_type, item_id, file_path, title, artist, duration_ms,
             clock_id, slot_idx}
            or None if no clock is assigned, no slots, or every slot's
            picker returned None (e.g. empty break, voice track out of
            window).

        Each call advances the cursor past the slot whose picker
        produced the returned item. Hour rollover resets the cursor.
        Safe to call from any thread.
        """
        if now is None:
            now = datetime.now()
        dow = int(now.weekday())
        hour = int(now.hour)
        hour_key = (dow, hour)
        # _active_hour_key is None only before the first pick after this
        # engine was created, i.e. after a restart or crash recovery.
        # A normal hour rollover still resets to slot 0 (QA ⚠19).
        cold_start = getattr(self, "_active_hour_key", None) is None
        if getattr(self, "_active_hour_key", None) != hour_key:
            self._clock_slot_cursor = 0
            self._active_hour_key = hour_key

        # Song delete / Category Move / clock save bump the DB's data
        # generation → drop the 60s plan + air-time caches right away.
        gen = getattr(self._db, "data_generation", 0)
        if gen != getattr(self, "_seen_data_generation", gen):
            self.invalidate_rotation_cache()
        self._seen_data_generation = gen

        # Phase F-Final S4: force_clocks override layer → grid fallback
        # (core.clock_resolver — the same rule the indicator uses).
        from core.clock_resolver import resolve_clock
        try:
            res = resolve_clock(self._db, now)
        except Exception as exc:
            log.debug(f"pick_next_item: get_active_clock failed: {exc}")
            return None
        if not res:
            return None
        clock_id: int = int(res["id"])
        # Slot cursor belongs to ONE clock — a force override starting
        # mid-hour (or a grid edit) must restart at slot 0 instead of
        # indexing the new clock with the old clock's position.
        if getattr(self, "_cursor_clock_id", None) != clock_id:
            self._clock_slot_cursor = 0
            self._cursor_clock_id = clock_id

        try:
            slots = self._db.get_clock_slots(clock_id)
        except Exception as exc:
            log.debug(f"pick_next_item: get_clock_slots failed: {exc}")
            return None
        if not slots:
            return None
        slots = self._apply_category_air_time(slots, clock_id, now)

        # Phase E5: stash per-pick context so _pick_song can consult
        # the rotation engine (which needs clock_id + hour)
        self._current_pick_clock_id = int(clock_id)
        self._current_pick_hour     = int(hour)
        self._current_pick_now      = now

        n = len(slots)
        if cold_start:
            # Resume where the Final Log says this clock left off this
            # hour, instead of replaying its top-of-hour elements mid-hour
            # (QA ⚠20, 2026-10-18). Only scheduler-dispatched rows of the
            # SAME clock in the CURRENT local hour count, so another clock,
            # an earlier hour or day, manual plays and legacy rows without
            # clock_id all leave the cursor at slot 0.
            since = now.strftime("%Y-%m-%d %H:00:00")
            try:
                last = self._db.get_last_clock_slot_play(clock_id, since)
                last = None if last is None else int(last)
            except Exception as exc:
                log.debug(f"pick_next_item: resume lookup skipped: {exc}")
                last = None
            if last is not None:
                self._clock_slot_cursor = (last + 1) % n
                if getattr(self._peek_local, "fired", None) is None:
                    log.info(f"scheduler: resumed clock {clock_id} at slot "
                             f"{self._clock_slot_cursor} (last aired slot "
                             f"{last} since {since})")
        cursor = int(getattr(self, "_clock_slot_cursor", 0)) % n
        for offset in range(n):
            idx = (cursor + offset) % n
            slot = slots[idx]
            stype = (slot["slot_type"] or "").strip().lower().replace(" ", "_")

            picker = {
                "song":         self._pick_song,
                "jingle":       self._pick_jingle,
                "sweeper":      self._pick_sweeper,
                "station_id":   self._pick_station_id,
                "voice_track":  self._pick_voice_track,
                "break":        self._pick_break,
                # Legacy 'spot' rows behave like Break.
                "spot":         self._pick_break,
            }.get(stype)

            if picker is None:
                continue

            try:
                # _pick_break also takes `now`; others ignore it.
                if stype in ("break", "spot"):
                    item = picker(slot, now)
                else:
                    item = picker(slot)
            except Exception as exc:
                log.warning(f"pick_next_item: picker {stype} failed: {exc}")
                item = None
            if item is None:
                continue
            self._clock_slot_cursor = (idx + 1) % n
            item["clock_id"] = clock_id
            item["slot_idx"] = idx
            # Phase 2 (2026-05-17) — cursor advanced; the queue's
            # "what's next" view has materially changed. UI consumers
            # listening on queue_changed re-render with the new peek_next.
            # SUPPRESSED while peek_next runs (it advances the cursor
            # inside try/finally for simulation; emitting there causes
            # a feedback storm because Studio's handler re-calls
            # peek_next → 5 more emits → exponential). Real commits
            # (via _compute_next_song's call path) fire the signal.
            if not self._suppress_queue_emit:
                try:
                    self.queue_changed.emit()
                except Exception as exc:
                    log.debug(
                        f"queue_changed emit (advance) failed: {exc}")
            return item
        return None

    def _apply_category_air_time(self, slots, clock_id: int,
                                 now: datetime) -> list:
        """This hour's view of the clock with category air-time tags
        applied (see core.category_air_time). Never raises — on any
        error the clock plays exactly as built."""
        try:
            from core.category_air_time import (
                apply_air_time, tagged_categories_at)
            if time.monotonic() - self._air_time_at >= 60.0:
                parts = self._db.get_all_category_dayparts() or []
                cats = sorted({int(p["category_id"]) for p in parts})
                playable: set = set()
                if cats:
                    marks = ",".join("?" * len(cats))
                    playable = {int(r[0]) for r in self._db._conn().execute(
                        f"SELECT DISTINCT category_id FROM songs "
                        f"WHERE is_enabled = 1 AND category_id IN ({marks})",
                        cats).fetchall()}
                sig = (tuple(sorted(
                           (int(p["category_id"]), p.get("day_of_week"),
                            int(p["hour_start"]), int(p["hour_end"]))
                           for p in parts)), frozenset(playable))
                prev_sig = getattr(self, "_air_time_sig", None)
                if prev_sig is not None and prev_sig != sig:
                    self._queue_dirty = True    # emitted by _on_tick
                self._air_time_sig = sig
                self._air_time_parts = parts
                self._air_time_playable = playable
                self._air_time_names = {
                    int(p["category_id"]): p.get("category_name")
                    for p in parts}
                self._air_time_at = time.monotonic()
            tagged = [c for c in tagged_categories_at(
                          self._air_time_parts, now.weekday(), now.hour)
                      if c in self._air_time_playable]
            if not tagged:
                return slots
            seed = f"{now.date().isoformat()}|{now.hour}|{int(clock_id)}"
            out, swaps = apply_air_time(slots, tagged, seed,
                                        self._air_time_names)
            key = (now.date(), now.hour, int(clock_id))
            if key not in self._air_time_logged:
                self._air_time_logged = {
                    k for k in self._air_time_logged if k[0] == now.date()}
                self._air_time_logged.add(key)
                names = self._air_time_names
                if swaps:
                    desc = ", ".join(
                        f"{names.get(old, 'All Songs') if old else 'All Songs'}"
                        f" → {names.get(new, new)}"
                        for new, old in swaps.items())
                    log.info(f"[air-time] {now:%H}:00 clock={clock_id}: "
                             f"{desc}")
                present = {s["category_id"] for s in slots
                           if "category_id" in s.keys()}
                for c in tagged:
                    if c in swaps or c in present:
                        continue          # placed / already in the clock
                    log.warning(f"[air-time] {now:%H}:00 clock={clock_id}: "
                                f"{names.get(c, c)!r} could not be placed "
                                f"— no free song category left to replace")
            return out
        except Exception as exc:
            log.warning(f"[air-time] skipped (clock plays as built): {exc}")
            return slots

    def pick_next_song(self, now: Optional[datetime] = None) -> Optional[dict]:
        """Backward-compat wrapper. Loops pick_next_item until a 'song'
        item is found (or budget exhausted). Repackages into the legacy
        {song, clock_id, slot_idx} shape so existing call sites keep
        working."""
        for _ in range(32):   # safety bound — clocks rarely exceed 32 slots
            item = self.pick_next_item(now=now)
            if item is None:
                return None
            if item.get("item_type") == "song":
                return {
                    "song": {
                        "id":          item.get("item_id"),
                        "title":       item.get("title"),
                        "artist":      item.get("artist"),
                        "file_path":   item.get("file_path"),
                        "duration_ms": item.get("duration_ms"),
                    },
                    "clock_id": item.get("clock_id"),
                    "slot_idx": item.get("slot_idx"),
                }
        return None

    def peek_next(self, n: int = 5,
                  now: Optional[datetime] = None) -> list[dict]:
        """Read-only preview of the next ``n`` items the scheduler would
        dispatch — without mutating any internal state.

        Studio v3's Up Coming panel needs to display upcoming items but
        must NOT cause the dispatch cursor to skip slots in the actual
        broadcast. This method snapshots every mutable scheduler state
        variable touched by the pick-pipeline (``_clock_slot_cursor``,
        ``_active_hour_key``, ``_fired_breaks``), calls ``pick_next_item``
        ``n`` times in a try/finally, and restores the snapshot in
        ``finally`` regardless of success or exception.

        Returns:
            list of item dicts (same shape as ``pick_next_item``), in
            dispatch order. Length ≤ ``n``. Empty list if no clock is
            assigned, or if every reachable slot's picker returns None.

        Notes:
            - Per-type pickers do read-only DB queries and ``random.choice``
              over candidate sets. Because the random state advances on
              each call, repeating ``peek_next`` may return different
              song picks for ``random_from_category`` slots — the
              CURSOR sequence is deterministic, the song identity is
              not. Slots backed by ``specific_song_id`` remain
              deterministic.
            - Safe to call from any thread (matches ``pick_next_item``).
        """
        try:
            n = max(0, int(n))
        except (TypeError, ValueError):
            return []
        if n == 0:
            return []

        # Snapshot every state variable touched by the pick pipeline.
        # _fired_breaks: _pick_break writes to a per-thread SIMULATION
        # copy while we peek; the real set is never replaced, so a key
        # the scheduler thread adds mid-peek can't be lost (2026-10-17).
        saved_cursor = self._clock_slot_cursor
        saved_hour_key = self._active_hour_key
        saved_cursor_clock = getattr(self, "_cursor_clock_id", None)
        saved_sim_fired = getattr(self._peek_local, "fired", None)
        # Restore already-aired breaks first so the preview can't show a
        # spot that went out before a restart (QA ⚠23).
        self._seed_fired_from_log(now or datetime.now())
        self._peek_local.fired = self._fired_snapshot()
        # Phase 2 — block queue_changed emission while we simulate
        # dispatches. Without this gate every peek_next would emit
        # `n` redundant signals, and Studio's `_on_scheduler_queue_changed`
        # handler re-calls peek_next → feedback storm (2026-05-17 bug
        # observed live: "NEXT chip frozen" with high queue_changed
        # event traffic).
        saved_suppress = self._suppress_queue_emit
        self._suppress_queue_emit = True

        out: list[dict] = []
        try:
            for _ in range(n):
                # Per-pick guard (2026-07-04): one failing simulated
                # pick must degrade to a SHORTER preview, not kill the
                # whole peek — the overnight session lost its Up Coming
                # panel to a single deep-picker exception, and the app
                # hard-crashed ~50s later. Traceback logged so the next
                # occurrence pinpoints the real file:line.
                try:
                    item = self.pick_next_item(now=now)
                except Exception:
                    import traceback as _tb
                    log.warning("peek_next: simulated pick failed — "
                                "returning partial preview\n"
                                f"{_tb.format_exc()}")
                    break
                if item is None:
                    break
                out.append(item)
        finally:
            # Restore unconditionally — covers both the success path and
            # any exception thrown deep inside a picker. The scheduler's
            # actual dispatch sequence is unchanged after this method
            # returns.
            self._clock_slot_cursor = saved_cursor
            self._active_hour_key = saved_hour_key
            self._cursor_clock_id = saved_cursor_clock
            self._peek_local.fired = saved_sim_fired
            self._suppress_queue_emit = saved_suppress
        return out

    # ── Per-type pickers ──────────────────────────────────────────────────

    @staticmethod
    def _slot_mode(slot) -> str:
        """Resolve the selection_mode field with a sane default."""
        m = (slot["selection_mode"]
             if "selection_mode" in slot.keys() else None) or "random_from_category"
        return str(m).strip().lower()

    @staticmethod
    def _slot_item_id(slot) -> Optional[int]:
        v = slot["item_id"] if "item_id" in slot.keys() else None
        return int(v) if v else None

    @staticmethod
    def _slot_category_id(slot) -> Optional[int]:
        v = slot["category_id"] if "category_id" in slot.keys() else None
        return int(v) if v else None

    def _active_rotation_decisions(self) -> dict:
        """Cached lookup of today's APPROVED rotation-plan decisions
        for the current pick context (BUG-2/BUG-3 fix).

        Returns {'active': bool, 'rest_ids': set[int], 'picks': list}.
        Inactive shape when: no pick context (direct _pick_song calls),
        no rotation engine installed, engine disabled, plan missing /
        pending / discarded, or ANY error (broadcast safety — the AI
        must never take the station down; log.debug and carry on).

        Memoised per (date, clock_id, hour) on the instance so
        peek_next's 5 simulated picks per refresh cost one query total.
        Signal-free, Qt-free, read-only — safe on the scheduler thread
        and inside peek simulations.
        """
        inactive = {"active": False, "rest_ids": set(), "picks": []}
        try:
            clock_id = self._current_pick_clock_id
            hour     = self._current_pick_hour
            if clock_id is None or hour is None:
                return inactive
            if (self._rotation_engine is None
                    or not self._rotation_engine.is_enabled()):
                return inactive
            now = getattr(self, "_current_pick_now", None)
            pick_date = (now.date() if isinstance(now, datetime)
                         else date.today()).isoformat()
            key = (pick_date, int(clock_id), int(hour))
            # 60s TTL so a plan approved mid-hour goes live within a
            # minute (key alone would cache "inactive" until rollover).
            fresh = (time.monotonic() - self._rot_dec_cache_at) < 60.0
            if key == self._rot_dec_cache_key and fresh:
                return self._rot_dec_cache
            decisions = self._db.get_active_rotation_decisions(
                pick_date, int(clock_id), int(hour))
            # Plan approved / discarded / edited mid-hour → the Up
            # Coming view is stale. Flag it; _on_tick emits
            # queue_changed outside any peek simulation.
            sig = (bool(decisions.get("active")),
                   frozenset(decisions.get("rest_ids") or ()),
                   tuple(sorted(int(p["song_id"])
                                for p in decisions.get("picks") or [])))
            prev = getattr(self, "_rot_dec_sig", None)
            if prev is not None and prev[0] == key and prev[1] != sig:
                self._queue_dirty = True
            self._rot_dec_sig = (key, sig)
            self._rot_dec_cache_key = key
            self._rot_dec_cache = decisions
            self._rot_dec_cache_at = time.monotonic()
            return decisions
        except Exception as exc:
            log.debug(
                f"_active_rotation_decisions failed: {exc} "
                f"— treating rotation plan as inactive")
            return inactive

    def invalidate_rotation_cache(self) -> None:
        """Drop the memoised approved-plan decisions + category air-time
        snapshot so the next pick re-reads the DB. Call after anything
        that changes what a slot may air: Category Move, song delete,
        clock save, plan approval. Thread-safe enough: plain attribute
        writes the scheduler thread re-checks on its next pick."""
        self._rot_dec_cache_key = None
        self._rot_dec_cache_at = 0.0
        self._air_time_at = -1e9
        # Up Coming must re-peek even if nothing else ticks it.
        self._queue_dirty = True

    def _pick_song(self, slot) -> Optional[dict]:
        """Song pick — Phase F-Final C3 dispatch order:

           1. specific_song_id    → exact song
           2. specific_artist_id  → random song from that artist
           3. filter_json         → apply Jazler-style filter spec
           4. category_id (legacy F2.3 path) → random from category
                                              with energy/vocal pref

        Always applies separation rules (60-min artist / 4-hr song) at
        the end. Falls back to the unfiltered candidate set when
        separation eliminates everything; falls through to fallback
        category, then to any song.
        """
        import random
        # 1) specific song
        sid = slot["specific_song_id"] if "specific_song_id" in slot.keys() else None
        if sid:
            row = self._db.get_song(int(sid))
            # A pinned song that was disabled in the library must not
            # air — fall through to the artist/filter/category pickers.
            if row and ("is_enabled" not in row.keys()
                        or row["is_enabled"] is None
                        or int(row["is_enabled"]) == 1):
                return self._song_row_to_item({k: row[k] for k in row.keys()})
            if row:
                log.warning(f"_pick_song: pinned song {sid} is disabled "
                            f"— falling through")

        # 2) specific artist — random from artist's catalog. Songs hold
        #    the artist as TEXT (there is no songs.artist_id column — the
        #    old query referenced one, raised "no such column" and was
        #    swallowed, so an artist pin silently never worked; found
        #    2026-10-16). Match by the artists row's name.
        aid = slot["specific_artist_id"] if "specific_artist_id" in slot.keys() else None
        if aid:
            try:
                rows = self._db._conn().execute(
                    "SELECT s.* FROM songs s "
                    "WHERE s.is_enabled = 1 AND LOWER(s.artist) = LOWER("
                    " (SELECT name FROM artists WHERE id = ?))",
                    [int(aid)],
                ).fetchall()
            except Exception as exc:
                log.warning(f"_pick_song: artist pin {aid} query failed: {exc}")
                rows = []
            playable = [r for r in rows
                        if r["file_path"] and os.path.exists(r["file_path"])]
            rows = playable or rows
            if rows:
                _rc = random.choice(rows)
                return self._song_row_to_item({k: _rc[k] for k in _rc.keys()})

        # 3) filter_json — Jazler-style filter spec. Only REAL
        #    constraints count: a filter that just names the slot's
        #    category (how the Clock Editor saves a category pick) or is
        #    empty is no filter, so the slot keeps Rotation AI + the
        #    category path below (core/slot_filter.py, 2026-10-16).
        import json as _json
        from core.slot_filter import effective_filter, sound_code_only
        spec = effective_filter(slot)
        songs: list = []
        if spec:
            songs = self._songs_matching_filter_json(_json.dumps(spec))

        # 3.4) Honor the operator-approved daily plan (BUG-2 fix).
        #      When today's plan is approved/auto_applied, its pick/
        #      promote decisions for this (clock, hour) ARE what airs —
        #      the live consult (3.5) drops to a secondary fallback.
        #      Operator pins (steps 1-2) and filter_json matches still
        #      win: this only fires when `songs` is empty. Playability
        #      (enabled + file on disk) and the scheduler's existing
        #      separation vetoes still apply — no new veto invented.
        category_id = self._slot_category_id(slot)
        if category_id is None and sound_code_only(slot):
            try:
                r = self._db._conn().execute(
                    "SELECT id FROM categories WHERE name = ?",
                    [sound_code_only(slot)]).fetchone()
                category_id = int(r[0]) if r else None
            except Exception:
                category_id = None
        rot = self._active_rotation_decisions()
        rest_ids: set = rot["rest_ids"] if rot["active"] else set()
        # A slot swapped to an air-time category this hour skips the
        # plan picks: the plan was built for the clock's own categories,
        # so honoring it here would air the category the tag replaced.
        air_time_slot = "_air_time_from" in slot.keys()
        if (not songs and not air_time_slot
                and rot["active"] and rot["picks"]):
            try:
                recent_artists  = self._recent_artists(
                    self.SEPARATION_SAME_ARTIST_MIN)
                recent_song_ids = self._recent_song_ids(
                    self.SEPARATION_SAME_SONG_MIN)
                # Slot-category gate: a plan pick only airs in a slot of
                # the category it was planned FOR, and only while the
                # song still LIVES there (Category Move takes effect at
                # once). An all-songs slot (no category) takes any pick.
                cat_picks = [
                    p for p in rot["picks"]
                    if category_id is None or (
                        p.get("category_id") == category_id
                        and p.get("target_category_id") in (
                            None, category_id))
                ]
                playable = [
                    p for p in cat_picks
                    if p.get("file_path")
                    and os.path.exists(p["file_path"])
                    and int(p["song_id"]) not in recent_song_ids
                    and (p.get("artist") or "") not in recent_artists
                ]
                if playable:
                    chosen = random.choice(playable)
                    log.info(
                        f"[rotation] plan pick honored "
                        f"song_id={chosen['song_id']} "
                        f"action={chosen.get('action')} "
                        f"clock={self._current_pick_clock_id} "
                        f"hour={self._current_pick_hour}")
                    return self._song_row_to_item({
                        "id":          chosen["song_id"],
                        "file_path":   chosen["file_path"],
                        "title":       chosen.get("title"),
                        "artist":      chosen.get("artist"),
                        "duration_ms": chosen.get("duration_ms"),
                    })
            except Exception as exc:
                log.debug(
                    f"_pick_song: plan-pick honor failed: {exc} "
                    f"— falling through to consult/ladder")

        # 3.5) Phase E5 — Rotation AI consult (live weighted re-roll).
        #      Secondary to the plan picks above — only reached when the
        #      plan yielded nothing usable. Fires when:
        #      • rotation_engine is set (MainWindow installed it)
        #      • no filter_json + no specific_song / specific_artist (those
        #        are operator pins — AI must not override)
        #      • engine reports is_enabled (Settings toggle ON)
        #      • today's plan is approved or auto_applied (operator
        #        gave the green light, OR 5-PM safety net fired)
        #      NULL-category slots consult too (BUG-4 fix): the engine's
        #      pick_song_for_clock handles NULL/0 category itself via
        #      the all-songs pool.
        #      PERF (2026-07-02): the consult walks the WHOLE category
        #      pool with per-song history queries (~0.44s on a 316-song
        #      category). peek_next(5) display refreshes were paying
        #      5x that on the UI thread — sluggish app + starved 1Hz
        #      tick (frozen break countdown, missed spot windows). The
        #      consult is now DISPATCH-ONLY: peek simulations (flagged
        #      by _suppress_queue_emit) use the fast ladder instead —
        #      preview labels stay accurate (category pool is the
        #      same), only the AI-grade weighting is deferred to the
        #      real pick.
        if (not songs and self._rotation_engine is not None
                and not self._suppress_queue_emit):
            try:
                if self._rotation_engine.is_enabled():
                    from datetime import date as _date
                    today = _date.today().isoformat()
                    plan = self._db.get_ai_rotation_plan(today)
                    if plan and plan.get("status") in (
                            "approved", "auto_applied"):
                        ai_pick = self._rotation_engine.pick_song_for_clock(
                            clock_id=int(self._current_pick_clock_id or 0),
                            hour=int(self._current_pick_hour or 0),
                            primary_category_id=int(category_id or 0),
                            now=getattr(self, "_current_pick_now", None))
                        if ai_pick:
                            log.info(
                                f"[scheduler] rotation AI pick "
                                f"song_id={ai_pick.get('id')} "
                                f"clock={self._current_pick_clock_id} "
                                f"hour={self._current_pick_hour}")
                            return self._song_row_to_item({k: ai_pick[k] for k in ai_pick.keys()})
            except Exception as exc:
                log.debug(
                    f"_pick_song: rotation AI consult failed: {exc} "
                    f"— falling back to random + separation")

        # 4) legacy category-based path
        if not songs:
            energy = slot["energy_pref"] if "energy_pref" in slot.keys() else None
            vocal  = slot["vocal_pref"]  if "vocal_pref"  in slot.keys() else None
            try:
                songs = self._db.get_songs(
                    category_id=category_id,
                    energy=energy if energy and energy != "Any" else None,
                    vocal=vocal   if vocal  and vocal  != "Any" else None,
                    limit=120,
                )
            except Exception as exc:
                log.debug(f"_pick_song: get_songs failed: {exc}")
                songs = []

        # Fallbacks: slot.fallback_category_id, then any song
        if not songs:
            fb_id = (slot["fallback_category_id"]
                     if "fallback_category_id" in slot.keys() else None)
            if fb_id:
                try:
                    songs = self._db.get_songs(
                        category_id=int(fb_id), limit=120)
                except Exception:
                    songs = []
        if not songs:
            try:
                songs = self._db.get_songs(limit=120)
            except Exception:
                songs = []
        if not songs:
            return None

        # REST exclusion (BUG-3 fix): an active plan's rested songs
        # must not air via the normal ladder either. Applied at the
        # candidate-list level, before separation. Never-stall rule:
        # if resting empties the pool, keep the unfiltered set —
        # broadcast must never go silent because of the AI.
        if rest_ids:
            unrested = [s for s in songs
                        if int(s["id"]) not in rest_ids]
            if unrested:
                songs = unrested
            else:
                log.warning(
                    "[rotation] all candidates rested — "
                    "falling back unfiltered")

        recent_artists = self._recent_artists(self.SEPARATION_SAME_ARTIST_MIN)
        recent_song_ids = self._recent_song_ids(self.SEPARATION_SAME_SONG_MIN)
        eligible = [
            s for s in songs
            if int(s["id"]) not in recent_song_ids
            and (s["artist"] or "") not in recent_artists
        ]
        chosen = random.choice(eligible) if eligible else random.choice(songs)
        return self._song_row_to_item(
            chosen if isinstance(chosen, dict)
            else {k: chosen[k] for k in chosen.keys()})

    @staticmethod
    def _song_row_to_item(row: dict) -> dict:
        return {
            "item_type":   "song",
            "item_id":     int(row.get("id")) if row.get("id") else None,
            "file_path":   row.get("file_path"),
            "title":       row.get("title"),
            "artist":      row.get("artist"),
            "duration_ms": int(row.get("duration_ms") or 0),
        }

    def _songs_matching_filter_json(self, filter_json: str) -> list:
        """Apply a Jazler-style filter spec stored in clock_slots.filter_json.
        Returns rows from `songs` matching the spec.

        Filter shape:
            {"sound_code": "Hot", "era": "2000s", "vocal": "vocal",
             "year_min": 2000, "year_max": 2024,
             "priority_min": 1, "priority_max": 9,
             "bpm_min": 90, "bpm_max": 130}
        Any key omitted = no constraint on that axis.
        """
        import json as _json
        try:
            spec = _json.loads(filter_json) if filter_json else {}
        except Exception:
            return []
        sql = ("SELECT s.* FROM songs s "
               "LEFT JOIN categories c ON s.category_id = c.id "
               "WHERE s.is_enabled = 1")
        params: list = []
        # Sound Code = Category name
        sc = spec.get("sound_code")
        if sc and sc not in ("All", "all", ""):
            sql += " AND c.name = ?"; params.append(str(sc))
        # Era / vocal map to song columns when present
        era = spec.get("era")
        if era and era not in ("All", "all", ""):
            sql += " AND s.era = ?"; params.append(str(era))
        vocal = spec.get("vocal")
        if vocal and vocal not in ("All", "all", ""):
            sql += " AND s.vocal = ?"; params.append(str(vocal))
        # Numeric ranges
        for col, key_min, key_max in [
            ("year",     "year_min",     "year_max"),
            ("priority", "priority_min", "priority_max"),
            ("bpm",      "bpm_min",      "bpm_max"),
        ]:
            v_min = spec.get(key_min); v_max = spec.get(key_max)
            try:
                if v_min not in (None, ""):
                    sql += f" AND s.{col} >= ?"; params.append(int(v_min))
                if v_max not in (None, ""):
                    sql += f" AND s.{col} <= ?"; params.append(int(v_max))
            except (TypeError, ValueError):
                pass
        sql += " LIMIT 240"
        try:
            return [{k: r[k] for k in r.keys()} for r in self._db._conn().execute(
                sql, params).fetchall()]
        except Exception as exc:
            log.debug(f"_songs_matching_filter_json failed: {exc}")
            return []

    def count_songs_matching_filter(self, filter_json: str) -> int:
        """Public helper for the modal Clock Editor's live "X Songs
        Available" indicator."""
        return len(self._songs_matching_filter_json(filter_json))

    # ── Playlists screen integration ─────────────────────────────────────

    def add_playlist_to_schedule(self, playlist_id: int) -> bool:
        """Premium Playlists screen — "Add to Schedule" action.

        Marks the playlist as scheduled (today / now). Returns True on
        success, False on failure. The actual broadcast wiring still
        runs through the Studio + auto_schedule path; this is the
        playlist-level toggle that the UI surfaces.

        Future Phase E work will replace this with smarter scheduling
        (slot allocation, day-part fit) — for now it's a deterministic
        toggle so the screen has live state."""
        from datetime import datetime as _dt
        now = _dt.now()
        try:
            self._db.set_playlist_scheduled(
                int(playlist_id),
                scheduled_day=now.strftime("%Y-%m-%d"),
                scheduled_time=now.strftime("%H:%M"),
            )
        except Exception as exc:
            log.warning(f"add_playlist_to_schedule({playlist_id}): {exc}")
            return False
        log.info(
            f"[scheduler] playlist {playlist_id} added to schedule "
            f"({now.strftime('%Y-%m-%d %H:%M')})")
        return True

    def remove_playlist_from_schedule(self, playlist_id: int) -> bool:
        """Inverse of add_playlist_to_schedule — clears scheduled_day/time."""
        try:
            self._db.set_playlist_scheduled(
                int(playlist_id), scheduled_day=None, scheduled_time=None)
        except Exception as exc:
            log.warning(f"remove_playlist_from_schedule({playlist_id}): {exc}")
            return False
        log.info(f"[scheduler] playlist {playlist_id} removed from schedule")
        return True

    def _pick_jingle(self, slot) -> Optional[dict]:
        """Jingle resolution: master library (`jingles`) is the canonical
        source — Clock Editor writes ``item_id`` referencing a jingles
        row when the operator pins one. The legacy `jingle_pads` path
        is kept as a fallback so any clock authored before the master-
        library migration still works.

        Mode dispatch:
          • specific + item_id   → master `jingles` row ONLY. (The old
                                   fallback to `jingle_pads` by the same
                                   id aired an UNRELATED pad whenever the
                                   pinned jingle was disabled — the two
                                   tables have separate id spaces.)
        Every path skips rows whose file is missing on disk (same
        hardening as _pick_sweeper) so a broken row can't stall air.
          • random_from_category + cat_id → legacy pad-grid path
                                   (cat_id interpreted as pallet_id).
                                   The master library doesn't map to
                                   pallets, so this path stays on pads.
          • random_any (default)  → random pick from the master library;
                                   falls back to active pads when the
                                   library is empty (greenfield install)."""
        import random
        mode = self._slot_mode(slot)
        item_id = self._slot_item_id(slot)
        cat_id  = self._slot_category_id(slot)   # legacy: interpreted as pallet_id

        if mode == "specific" and item_id:
            row = self._db._conn().execute(
                "SELECT * FROM jingles WHERE id = ? AND is_enabled = 1 "
                "AND file_path IS NOT NULL AND file_path != ''",
                [item_id]).fetchone()
            if row and _file_exists(row):
                return self._jingle_to_item(row)
            if row:
                log.warning(f"_pick_jingle: jingle id={item_id} file "
                            f"missing on disk — slot skipped")
            return None

        if mode == "random_from_category" and cat_id:
            pads = [p for p in self._db.get_jingle_pads_active(
                        pallet_id=cat_id) if _file_exists(p)]
            if pads:
                return self._jingle_pad_to_item(random.choice(pads))

        # random_any — master library first.
        try:
            jingles = self._db._conn().execute(
                "SELECT * FROM jingles WHERE is_enabled = 1 "
                "AND file_path IS NOT NULL AND file_path != ''"
            ).fetchall()
        except Exception:
            jingles = []
        jingles = [j for j in jingles if _file_exists(j)]
        if jingles:
            return self._jingle_to_item(random.choice(jingles))
        # Greenfield fallback — nothing playable in `jingles`, take a pad.
        pads = [p for p in self._db.get_jingle_pads_active()
                if _file_exists(p)]
        if not pads:
            return None
        return self._jingle_pad_to_item(random.choice(pads))

    @staticmethod
    def _jingle_pad_to_item(row) -> dict:
        return {
            "item_type":   "jingle",
            "item_id":     int(row["id"]) if row and "id" in row.keys() else None,
            "file_path":   row["file_path"] if row and "file_path" in row.keys() else None,
            "title":       row["label"]     if row and "label"     in row.keys() else "Jingle",
            "artist":      "JINGLE",
            # item_id here is a jingle_pads.id — NOT a jingles.id, so it
            # must never be logged as broadcast_log.jingle_id.
            "_source":     "pad",
            "duration_ms": int(row["duration_ms"] or 0)
                           if row and "duration_ms" in row.keys() else 0,
        }

    @staticmethod
    def _jingle_to_item(row) -> dict:
        """Translate a `jingles` library row into a scheduler item dict.
        Same shape as _jingle_pad_to_item so the deck dispatch path
        doesn't care which source the row came from."""
        return {
            "item_type":   "jingle",
            "item_id":     int(row["id"]) if row and "id" in row.keys() else None,
            "file_path":   row["file_path"] if row and "file_path" in row.keys() else None,
            "title":       row["name"]     if row and "name"     in row.keys() else "Jingle",
            "artist":      "JINGLE",
            "duration_ms": int(row["duration_ms"] or 0)
                           if row and "duration_ms" in row.keys() else 0,
        }

    def _pick_sweeper(self, slot) -> Optional[dict]:
        """Pick a playable sweeper for the slot. 2026-05-17 hardening:
        filters out sweepers with missing/empty file_path AND files
        that don't exist on disk — broken rows used to slip through,
        Studio's dispatch loop then skipped them, eventually exhausted
        its safety budget, and the broadcast went idle ("software stops
        playing anything"). Returning None here lets the scheduler's
        slot walker advance to the next slot cleanly."""
        import os
        import random
        mode = self._slot_mode(slot)
        item_id = self._slot_item_id(slot)

        if mode == "specific" and item_id:
            row = self._db._conn().execute(
                "SELECT * FROM sweepers WHERE id = ? AND is_enabled = 1",
                [item_id]).fetchone()
            if not row:
                return None
            fp = row["file_path"] if "file_path" in row.keys() else None
            if not fp or not os.path.exists(fp):
                log.warning(
                    f"_pick_sweeper: specific sweeper id={item_id} "
                    f"has missing/empty file_path={fp!r} — slot skipped")
                return None
            return self._sweeper_to_item(row)

        # Random — filter to playable rows so a broken sweeper can't
        # cascade Studio's _compute_next_song into the broken-skip
        # budget loop.
        all_rows = list(self._db.get_sweepers_active())
        playable = []
        for r in all_rows:
            try:
                fp = r["file_path"] if "file_path" in r.keys() else None
            except Exception:
                fp = None
            if fp and os.path.exists(fp):
                playable.append(r)
        if not playable:
            if all_rows:
                log.warning(
                    f"_pick_sweeper: {len(all_rows)} active sweepers "
                    f"exist but none have a playable file_path — "
                    f"slot skipped (operator: check Sweepers Library)")
            return None
        return self._sweeper_to_item(random.choice(playable))

    @staticmethod
    def _sweeper_to_item(row) -> dict:
        return {
            "item_type":   "sweeper",
            "item_id":     int(row["id"]) if row else None,
            "file_path":   row["file_path"] if row and "file_path" in row.keys() else None,
            "title":       row["name"]      if row and "name"      in row.keys() else "Sweeper",
            "artist":      "SWEEPER",
            "duration_ms": int(row["duration_ms"] or 0)
                           if row and "duration_ms" in row.keys() else 0,
            # 2026-05-17 — surface the sweeper's `position` field so
            # Studio's overlay-vs-deck decision in _compute_next_song
            # works correctly. Without this, overlay-positioned
            # sweepers (Start of Song / Before End / Bridge at End /
            # Custom) always fell through to the deck-load branch.
            "position":    (row["position"]
                            if row and "position" in row.keys() else "") or "",
            # 2026-07-25 — carry the mix fields too. Previously only the
            # MANUAL play path (Studio._on_play_sweeper_overlay) read
            # these off the row, so an auto-dispatched sweeper silently
            # fell back to volume 100 / offset 0 and the per-sweeper
            # settings in the Sweeper Editor did nothing on air.
            # Columns are added by _ensure_sweepers_columns (idempotent),
            # so guard with key checks for very old DBs.
            "volume_sweeper_pct": (
                int(row["volume_sweeper_pct"])
                if row and "volume_sweeper_pct" in row.keys()
                and row["volume_sweeper_pct"] is not None else 100),
            "volume_song_pct": (
                int(row["volume_song_pct"])
                if row and "volume_song_pct" in row.keys()
                and row["volume_song_pct"] is not None else 100),
            "offset_seconds": (
                float(row["offset_seconds"])
                if row and "offset_seconds" in row.keys()
                and row["offset_seconds"] is not None else 0.0),
            "fade_seconds": (
                float(row["fade_seconds"])
                if row and "fade_seconds" in row.keys()
                and row["fade_seconds"] is not None else 0.5),
        }

    def _pick_station_id(self, slot) -> Optional[dict]:
        """Station IDs are jingles WHERE category='Station ID'."""
        import random
        mode = self._slot_mode(slot)
        item_id = self._slot_item_id(slot)

        if mode == "specific" and item_id:
            row = self._db._conn().execute(
                "SELECT * FROM jingles WHERE id = ? "
                "AND category = 'Station ID' AND is_enabled = 1",
                [item_id]).fetchone()
            return (self._station_id_to_item(row)
                    if row and _file_exists(row) else None)

        rows = [r for r in self._db.get_station_ids_active()
                if _file_exists(r)]
        if not rows:
            return None
        return self._station_id_to_item(random.choice(rows))

    @staticmethod
    def _station_id_to_item(row) -> dict:
        return {
            "item_type":   "station_id",
            "item_id":     int(row["id"]) if row else None,
            "file_path":   row["file_path"] if row and "file_path" in row.keys() else None,
            "title":       row["name"]      if row and "name"      in row.keys() else "Station ID",
            "artist":      "STATION ID",
            "duration_ms": int(row["duration_ms"] or 0)
                           if row and "duration_ms" in row.keys() else 0,
        }

    def _pick_voice_track(self, slot) -> Optional[dict]:
        """Voice tracks filter by today between valid_from..valid_to.
        Returns None if no valid track is in the window — caller skips
        the slot."""
        import random
        from datetime import datetime as _dt
        mode = self._slot_mode(slot)
        item_id = self._slot_item_id(slot)
        today_str = _dt.now().strftime("%Y-%m-%d")

        if mode == "specific" and item_id:
            row = self._db._conn().execute(
                "SELECT * FROM voice_tracks WHERE id = ? AND is_active = 1 "
                "AND (valid_from IS NULL OR valid_from <= ?) "
                "AND (valid_to   IS NULL OR valid_to   >= ?)",
                [item_id, today_str, today_str]).fetchone()
            return self._voice_track_to_item(row) if row else None

        rows = list(self._db.get_voice_tracks(today_str))
        if not rows:
            return None
        return self._voice_track_to_item(random.choice(rows))

    @staticmethod
    def _voice_track_to_item(row) -> dict:
        return {
            "item_type":   "voice_track",
            "item_id":     int(row["id"]) if row else None,
            "file_path":   row["file_path"] if row and "file_path" in row.keys() else None,
            "title":       row["label"] if (row and "label" in row.keys() and row["label"])
                           else (row["name"] if row and "name" in row.keys() else "Voice Track"),
            "artist":      "VOICE TRACK",
            "duration_ms": int(row["duration_ms"] or 0)
                           if row and "duration_ms" in row.keys() else 0,
        }

    def _pick_break(self, slot, now: datetime) -> Optional[dict]:
        """A Break slot pulls the next pending campaign for the current
        hour — returns the first active spot file. Coordinates with the
        spot_due tick path via the shared _fired_breaks dedupe set so we
        don't double-fire a campaign that the per-tick scheduler already
        sent."""
        try:
            day_breaks = list(self._db.get_active_breaks_for_day(int(now.weekday())))
        except Exception:
            return None
        if not day_breaks:
            return None
        # Filter to campaigns whose break_time falls in the current hour,
        # is actually DUE (break_dt <= now + SPOT_TOLERANCE_S — never a
        # break scheduled later this hour), and isn't already fired.
        # While peek_next simulates, use its per-thread copy instead of
        # the real set (race fix 2026-10-17).
        sim_fired = getattr(self._peek_local, "fired", None)
        if sim_fired is None:
            # Breaks that aired before a restart must not air again
            # (QA ⚠23). Idempotent per day; a peek simulation was already
            # seeded in peek_next before its snapshot.
            self._seed_fired_from_log(now)
        fired = sim_fired if sim_fired is not None else self._fired_breaks
        cur_hour = int(now.hour)
        for br in day_breaks:
            br_time = (br["break_time"] or "").strip()
            if not br_time:
                continue
            try:
                br_h = int(br_time.split(":")[0])
            except (ValueError, IndexError):
                continue
            if br_h != cur_hour:
                continue
            br_dt = self._break_time_to_dt(br_time, now)
            if br_dt is None or (br_dt - now).total_seconds() > self.SPOT_TOLERANCE_S:
                continue
            campaign_id = int(br["campaign_id"])
            dedupe_key = (campaign_id, br_time)
            if dedupe_key in fired:
                continue
            # Pick the first playable spot file for this campaign.
            try:
                files = list(self._db.get_spot_files(campaign_id))
            except Exception:
                files = []
            chosen = None
            for sf in files:
                fp = sf["file_path"] if "file_path" in sf.keys() else None
                is_act = (sf["is_active"] if "is_active" in sf.keys() else 1)
                if fp and int(is_act or 0):
                    chosen = sf
                    break
            if chosen is None:
                continue
            if sim_fired is not None:
                sim_fired.add(dedupe_key)
            else:
                with self._fired_lock:
                    self._fired_breaks.add(dedupe_key)
            return {
                "item_type":   "spot",
                "item_id":     campaign_id,
                "campaign_id": campaign_id,
                "file_path":   chosen["file_path"]
                               if "file_path" in chosen.keys() else None,
                "title":       br["campaign_name"] or "Spot",
                "artist":      "Spot · auto-aired",
                "duration_ms": int(chosen["duration_ms"] or 0)
                               if "duration_ms" in chosen.keys() else 0,
            }
        return None

    # ── Separation rule helpers ──────────────────────────────────────────

    def _recent_artists(self, minutes: int) -> set:
        """Distinct song artists played in the last `minutes` minutes."""
        from datetime import datetime as _dt, timedelta as _td
        cutoff = (_dt.now() - _td(minutes=int(minutes))).strftime(
            "%Y-%m-%d %H:%M:%S")
        try:
            rows = self._db._conn().execute(
                "SELECT DISTINCT s.artist FROM broadcast_log bl "
                "LEFT JOIN songs s ON bl.song_id = s.id "
                "WHERE bl.played_at >= ? AND bl.entry_type = 'song' "
                "AND s.artist IS NOT NULL AND s.artist != ''",
                [cutoff],
            ).fetchall()
        except Exception:
            return set()
        # Placeholder artists (Unknown Artist etc.) are missing
        # metadata, not a real artist — 115+ untagged songs must not
        # separation-block each other (rotation audit 2026-07-02).
        try:
            from core.database import Database
            placeholders = Database.PLACEHOLDER_ARTISTS
        except Exception:
            placeholders = frozenset()
        return {r[0] for r in rows
                if r[0] and str(r[0]).strip().casefold()
                not in placeholders}

    def _recent_song_ids(self, minutes: int) -> set:
        from datetime import datetime as _dt, timedelta as _td
        cutoff = (_dt.now() - _td(minutes=int(minutes))).strftime(
            "%Y-%m-%d %H:%M:%S")
        try:
            rows = self._db._conn().execute(
                "SELECT DISTINCT bl.song_id FROM broadcast_log bl "
                "WHERE bl.played_at >= ? AND bl.entry_type = 'song' "
                "AND bl.song_id IS NOT NULL",
                [cutoff],
            ).fetchall()
        except Exception:
            return set()
        return {int(r[0]) for r in rows if r[0]}

    # ── Diagnostics ──────────────────────────────────────────────────────

    @property
    def tick_count(self) -> int:
        """How many ticks have fired since start. Useful for tests +
        debug overlays."""
        return self._tick_count
