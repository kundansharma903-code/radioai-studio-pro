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

        # Phase F2: clock-slot cursor for pick_next_song. Reset on hour
        # rollover so each hour starts at slot 0.
        self._clock_slot_cursor: int = 0
        self._active_hour_key: Optional[tuple[int, int]] = None

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
                return self._song_row_to_item(dict(row))

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
                return self._song_row_to_item(dict(random.choice(rows)))

        # 3) filter_json — Jazler-style filter spec
        fj = slot["filter_json"] if "filter_json" in slot.keys() else None
        songs: list = []
        if fj:
            songs = self._songs_matching_filter_json(fj)

        # 4) legacy category-based path
        if not songs:
            category_id = self._slot_category_id(slot)
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

        recent_artists = self._recent_artists(self.SEPARATION_SAME_ARTIST_MIN)
        recent_song_ids = self._recent_song_ids(self.SEPARATION_SAME_SONG_MIN)
        eligible = [
            s for s in songs
            if int(s["id"]) not in recent_song_ids
            and (s["artist"] or "") not in recent_artists
        ]
        chosen = random.choice(eligible) if eligible else random.choice(songs)
        return self._song_row_to_item(
            chosen if isinstance(chosen, dict) else dict(chosen))

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
            return [dict(r) for r in self._db._conn().execute(
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
        """Jingle = a row from jingle_pads. selection_mode dispatches."""
        import random
        mode = self._slot_mode(slot)
        item_id = self._slot_item_id(slot)
        cat_id  = self._slot_category_id(slot)   # interpreted as pallet_id

        if mode == "specific" and item_id:
            row = self._db._conn().execute(
                "SELECT * FROM jingle_pads WHERE id = ? "
                "AND file_path IS NOT NULL AND file_path != ''",
                [item_id]).fetchone()
            return self._jingle_pad_to_item(row) if row else None

        if mode == "random_from_category" and cat_id:
            pads = list(self._db.get_jingle_pads_active(pallet_id=cat_id))
            if pads:
                return self._jingle_pad_to_item(random.choice(pads))

        # random_any (or fall-through from above)
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

    def _pick_sweeper(self, slot) -> Optional[dict]:
        import random
        mode = self._slot_mode(slot)
        item_id = self._slot_item_id(slot)

        if mode == "specific" and item_id:
            row = self._db._conn().execute(
                "SELECT * FROM sweepers WHERE id = ? AND is_enabled = 1",
                [item_id]).fetchone()
            return self._sweeper_to_item(row) if row else None

        rows = list(self._db.get_sweepers_active())
        if not rows:
            return None
        return self._sweeper_to_item(random.choice(rows))

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
