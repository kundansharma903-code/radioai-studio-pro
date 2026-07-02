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

        # Phase D3+ event queue (populated by D5; consumed by _on_tick)
        self._event_queue: list[ScheduledEvent] = []

        # Phase D4: today's break schedule (cached; refreshed at day rollover)
        self._loaded_breaks: list[dict] = []
        self._loaded_date: Optional[date] = None
        # Dedupe keys: (campaign_id, break_time) for spots already fired today;
        # ('warn', campaign_id, break_time) for 30s-warning that already fired.
        self._fired_breaks: set = set()

        # Phase F2: clock-slot cursor for pick_next_song. Reset on hour
        # rollover so each hour starts at slot 0.
        self._clock_slot_cursor: int = 0
        self._active_hour_key: Optional[tuple[int, int]] = None

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

    def set_rotation_engine(self, engine) -> None:
        """Install a RotationAIEngine handle. Pass None to detach
        (reverts to native random + separation pick)."""
        self._rotation_engine = engine

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
        # Active-clock tracking is its own try/except so a DB blip on
        # this path can never freeze the dispatch tick (which lives in
        # _dispatch_due_events above). Broadcast safety: keep the
        # 1Hz heartbeat alive at all costs.
        self._check_active_clock_change()

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
            now = datetime.now()
            dow = int(now.weekday())
            hour = int(now.hour)
            row = self._db.get_active_clock(dow, hour)
            if row is None:
                new_id = -1
                new_name = ""
            else:
                try:
                    new_id = int(row["id"])
                except (KeyError, IndexError, TypeError, ValueError):
                    new_id = -1
                try:
                    new_name = str(row["name"] or "")
                except (KeyError, IndexError, TypeError):
                    new_name = ""
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
                log.warning(f"break-schedule reload failed: {exc}")
                # Don't keep retrying every tick on failure — mark loaded
                # so next attempt happens at the next day rollover.
                self._loaded_date = today
                self._loaded_breaks = []
                self._fired_breaks.clear()
            else:
                self._fired_breaks.clear()
                # New day → yesterday's rotation-plan decisions are
                # stale; force a refetch on the next pick.
                self._rot_dec_cache_key = None
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
        self._loaded_breaks = [{k: r[k] for k in r.keys()} for r in rows]
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
        if getattr(self, "_active_hour_key", None) != hour_key:
            self._clock_slot_cursor = 0
            self._active_hour_key = hour_key

        # Phase F-Final S4: force_clocks override layer
        clock_id: Optional[int] = None
        try:
            fc = self._db.get_force_clock_for(now)
            if fc is not None:
                clock_id = int(fc["clock_id"])
        except Exception as exc:
            log.debug(f"pick_next_item: get_force_clock_for failed: {exc}")
        if clock_id is None:
            try:
                clock_row = self._db.get_active_clock(dow, hour)
            except Exception as exc:
                log.debug(f"pick_next_item: get_active_clock failed: {exc}")
                return None
            if not clock_row:
                return None
            clock_id = int(clock_row["id"])

        try:
            slots = self._db.get_clock_slots(clock_id)
        except Exception as exc:
            log.debug(f"pick_next_item: get_clock_slots failed: {exc}")
            return None
        if not slots:
            return None

        # Phase E5: stash per-pick context so _pick_song can consult
        # the rotation engine (which needs clock_id + hour)
        self._current_pick_clock_id = int(clock_id)
        self._current_pick_hour     = int(hour)
        self._current_pick_now      = now

        n = len(slots)
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
        # _fired_breaks is mutated inside _pick_break (line 826); we copy
        # the set so add/remove operations during the simulated picks
        # don't bleed back into real dispatch.
        saved_cursor = self._clock_slot_cursor
        saved_hour_key = self._active_hour_key
        saved_fired_breaks = set(self._fired_breaks)
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
                item = self.pick_next_item(now=now)
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
            self._fired_breaks = saved_fired_breaks
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
            self._rot_dec_cache_key = key
            self._rot_dec_cache = decisions
            self._rot_dec_cache_at = time.monotonic()
            return decisions
        except Exception as exc:
            log.debug(
                f"_active_rotation_decisions failed: {exc} "
                f"— treating rotation plan as inactive")
            return inactive

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
            if row:
                return self._song_row_to_item({k: row[k] for k in row.keys()})

        # 2) specific artist — random from artist's catalog
        aid = slot["specific_artist_id"] if "specific_artist_id" in slot.keys() else None
        if aid:
            try:
                rows = self._db._conn().execute(
                    "SELECT s.* FROM songs s "
                    "WHERE s.is_enabled = 1 AND "
                    "(s.artist_id = ? OR s.artist = "
                    " (SELECT name FROM artists WHERE id = ?))",
                    [int(aid), int(aid)],
                ).fetchall()
            except Exception:
                rows = []
            if rows:
                _rc = random.choice(rows)
                return self._song_row_to_item({k: _rc[k] for k in _rc.keys()})

        # 3) filter_json — Jazler-style filter spec
        fj = slot["filter_json"] if "filter_json" in slot.keys() else None
        songs: list = []
        if fj:
            songs = self._songs_matching_filter_json(fj)

        # 3.4) Honor the operator-approved daily plan (BUG-2 fix).
        #      When today's plan is approved/auto_applied, its pick/
        #      promote decisions for this (clock, hour) ARE what airs —
        #      the live consult (3.5) drops to a secondary fallback.
        #      Operator pins (steps 1-2) and filter_json matches still
        #      win: this only fires when `songs` is empty. Playability
        #      (enabled + file on disk) and the scheduler's existing
        #      separation vetoes still apply — no new veto invented.
        category_id = self._slot_category_id(slot)
        rot = self._active_rotation_decisions()
        rest_ids: set = rot["rest_ids"] if rot["active"] else set()
        if not songs and rot["active"] and rot["picks"]:
            try:
                recent_artists  = self._recent_artists(
                    self.SEPARATION_SAME_ARTIST_MIN)
                recent_song_ids = self._recent_song_ids(
                    self.SEPARATION_SAME_SONG_MIN)
                playable = [
                    p for p in rot["picks"]
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
        if not songs and self._rotation_engine is not None:
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
          • specific + item_id   → master `jingles` row (preferred);
                                   falls back to `jingle_pads.id` lookup
                                   for pre-migration slots that referenced
                                   the pad-grid table by id.
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
            # Prefer the master library.
            row = self._db._conn().execute(
                "SELECT * FROM jingles WHERE id = ? AND is_enabled = 1 "
                "AND file_path IS NOT NULL AND file_path != ''",
                [item_id]).fetchone()
            if row:
                return self._jingle_to_item(row)
            # Fallback: legacy pad-grid lookup (pre-migration clocks).
            row = self._db._conn().execute(
                "SELECT * FROM jingle_pads WHERE id = ? "
                "AND file_path IS NOT NULL AND file_path != ''",
                [item_id]).fetchone()
            return self._jingle_pad_to_item(row) if row else None

        if mode == "random_from_category" and cat_id:
            pads = list(self._db.get_jingle_pads_active(pallet_id=cat_id))
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
        if jingles:
            return self._jingle_to_item(random.choice(jingles))
        # Greenfield fallback — nothing in `jingles`, take a pad.
        pads = list(self._db.get_jingle_pads_active())
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
            return self._station_id_to_item(row) if row else None

        rows = list(self._db.get_station_ids_active())
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
        # Filter to campaigns whose break_time falls in the current hour
        # and aren't already in _fired_breaks.
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
            campaign_id = int(br["campaign_id"])
            dedupe_key = (campaign_id, br_time)
            if dedupe_key in self._fired_breaks:
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
            self._fired_breaks.add(dedupe_key)
            return {
                "item_type":   "spot",
                "item_id":     campaign_id,
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
        return {r[0] for r in rows if r[0]}

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
