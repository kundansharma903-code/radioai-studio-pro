"""
RadioAI Studio Pro — Rotation AI Engine (Time-Slot Freshness).

Phase D — implements the operator-locked algorithm:

  For each candidate song at hour H of clock C:
      slot_age_days  = days since last play in this hour-of-day
      overall_age_hr = hours since last play anywhere

      base_weight  = lookup(slot_age_days) on the operator-approved curve
          today      → 0.00  (hard veto — already heard at this hour)
          1 day      → 0.05  (heavy penalty — heard yesterday at this hour)
          2 days     → 0.30
          3 days     → 0.60
          4 days     → 0.90
          5-6 days   → 1.00
          7+ days    → 1.00
          never      → 1.30  (boost — listener hasn't heard here)

      primary_boost = 1.20 if song.category_id == clock.primary else 1.0
      final_weight  = base_weight × primary_boost

      vetoes (final_weight → 0):
          overall_age_hr < 4                       (4-hour same-song rule)
          overall_age_hr < 1 AND same_artist       (1-hour artist rule)

  Pool = clock.primary_category ∪ sister_categories
  Pick = weighted_random(eligible, weights=final_weight)

Operator decisions (locked 2026-05-15):
  Q1  Sister groups symmetric (A/B/C/D mutually sisters)
  Q2  burn-score replaced by Time-Slot Freshness (this file)
  Q3  Continuous hourly tick + manual refresh
  Q4  Tier demotion = today-only veto via weight=0
  Q5  Soft inclusion — no DB row movement; pool expansion at pick time
  Q6  Stop AI Engine toggle (host wires)
  Q7  Phase 2 rollout — preview + approve gate + 5 PM auto-apply

Engine ownership:
  • MainWindow instantiates ONE RotationAIEngine at boot.
  • Hub screen subscribes to engine_state_changed + tick_completed.
  • Phase E will wire SchedulerEngine.pick_next_item to consult
    rotation_decisions before random + separation fallback.

Threading:
  Same QThread + QTimer "object on a thread" pattern as
  core/scheduler/engine.py + core/sotg_transcription_engine.py.
  All DB work runs on the engine thread; signals auto-marshal back to
  the main thread for the UI.
"""

from __future__ import annotations

import logging
import random
import threading
from datetime import date as _date, datetime, timedelta
from typing import Optional

from PyQt6.QtCore import QObject, QThread, QTimer, Qt, pyqtSignal, QMetaObject

from core.database import Database
from core.settings import Settings

log = logging.getLogger("RotationAI")


# ── Settings keys (single source of truth — UI + engine read/write here) ──
KEY_ENGINE_ENABLED   = "rotation_ai_engine_enabled"     # '1' | '0'
KEY_LAST_TICK_AT     = "rotation_ai_last_tick_at"       # ISO ts
KEY_LAST_ERROR       = "rotation_ai_last_error"          # str or ""
KEY_LAST_PLAN_DATE   = "rotation_ai_last_plan_date"      # YYYY-MM-DD
KEY_LAST_PURGE_DATE  = "rotation_ai_last_purge_date"     # YYYY-MM-DD


# ── Engine states (string enum) ────────────────────────────────────────────
STATE_OFF     = "OFF"     # disabled by operator
STATE_WARMING = "WARMING" # boot, first tick pending
STATE_ON      = "ON"      # ticking healthily
STATE_ERROR   = "ERROR"   # last tick raised — needs refresh


class RotationAIEngine(QObject):
    """Time-Slot Freshness rotation engine.

    Public surface is thread-safe — caller code in any thread can read
    state via the getters; mutations go through the queued QTimer tick.
    """

    # ── Algorithm constants (operator-locked) ─────────────────────────

    # Weight curve: slot_age_days → base weight
    SLOT_AGE_WEIGHTS = {
        0: 0.00,    # today — hard veto
        1: 0.05,    # yesterday — heavy penalty
        2: 0.30,
        3: 0.60,
        4: 0.90,
        5: 1.00,
        6: 1.00,
    }
    WEIGHT_DEFAULT = 1.00       # 7+ days slot_age
    WEIGHT_NEVER   = 1.30       # never played in slot — boost
    PRIMARY_BOOST  = 1.20        # song.category == clock primary

    OVERALL_RECENT_HRS = 4       # 4-hour same-song veto
    OVERALL_ARTIST_HRS = 1       # 1-hour same-artist veto

    # Tick interval — 1 hour (operator's Q3 = (c) continuous)
    TICK_INTERVAL_MS = 3_600_000
    BOOT_DELAY_MS    = 5_000     # first tick 5s after start

    # ── Signals ───────────────────────────────────────────────────────

    engine_state_changed = pyqtSignal(str)        # ON/WARMING/ERROR/OFF
    tick_completed       = pyqtSignal(int, dict)  # plan_id, summary
    error_occurred       = pyqtSignal(str)
    started              = pyqtSignal()
    stopped              = pyqtSignal()

    def __init__(self, db: Optional[Database] = None,
                  tick_interval_ms: Optional[int] = None,
                  parent=None):
        super().__init__(parent)
        self._db = db or Database()
        self._tick_interval_ms = max(
            60_000, int(tick_interval_ms or self.TICK_INTERVAL_MS))
        self._thread: Optional[QThread] = None
        self._timer: Optional[QTimer] = None
        self._running: bool = False
        self._lock = threading.Lock()
        self._state: str = STATE_OFF
        # Deterministic RNG seeded per process — pickle-safe + lets
        # tests fix randomness via random.seed() if needed
        self._rng = random.Random()
        # Cache today's plan_id to avoid repeated lookups during the
        # same tick window. Reset on day rollover or stop().
        self._cached_plan_date: Optional[str] = None
        self._cached_plan_id: Optional[int] = None

    # ── Lifecycle ─────────────────────────────────────────────────────

    def is_running(self) -> bool:
        return self._running

    def is_enabled(self) -> bool:
        """Engine runs only when operator has flipped the toggle on.
        Default ON (first launch). Operator can stop via the Hub's
        Stop AI Engine button which sets this to '0'."""
        v = Settings().get(KEY_ENGINE_ENABLED, "1") or "1"
        return str(v).strip() in ("1", "true", "True", "yes")

    def state(self) -> str:
        return self._state

    def start(self) -> None:
        """Spin up the QThread + tick timer. Idempotent. No-op when
        operator has disabled the engine via Settings."""
        with self._lock:
            if self._running:
                log.debug("rotation engine — already running")
                return
            self._running = True

        # Detach parent before moveToThread (Qt requirement)
        self.setParent(None)

        self._thread = QThread()
        self.moveToThread(self._thread)
        self._thread.started.connect(self._on_thread_started)
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.start()
        self._set_state(STATE_WARMING)
        log.info(
            f"RotationAIEngine started "
            f"(tick={self._tick_interval_ms}ms, "
            f"enabled={self.is_enabled()})")

    def stop(self) -> None:
        """Stop the tick timer + tear down the thread. Idempotent;
        safe from any thread."""
        with self._lock:
            if not self._running:
                return
            self._running = False

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
                    "rotation engine: thread did not exit in 2s; "
                    "terminating")
                self._thread.terminate()
                self._thread.wait(500)
            self._thread = None
        self._set_state(STATE_OFF)
        log.info("RotationAIEngine stopped")

    def shutdown(self) -> None:
        """Alias for stop — matches the SOTGTranscriptionEngine
        surface so MainWindow can call .shutdown() symmetrically."""
        self.stop()

    # ── Thread plumbing (runs on rotation engine thread) ──────────────

    def _on_thread_started(self) -> None:
        """Runs on the engine thread. Create the timer here so it
        lives on this thread + fires one initial tick after the boot
        delay so the operator sees a plan quickly on first launch.

        Phase H fix: previously a race could fire when the MainWindow
        tore the engine down (via stop()) before this slot finished —
        stop() set self._timer = None mid-flight, and our subsequent
        self._timer.start() crashed with AttributeError. Now we build
        the timer in a local variable, take the lock once to publish
        + check the running flag, and use the local for .start() so
        a concurrent stop() can no-op cleanly. Surfaces in test
        environments where MainWindow + engine are stood up and torn
        down rapidly; was theoretically possible during app shutdown."""
        t = QTimer()
        t.setInterval(self._tick_interval_ms)
        t.timeout.connect(self._on_tick)
        with self._lock:
            if not self._running:
                # stop() already ran — abandon the timer (it never
                # got assigned to self, so it'll be GC'd) and skip
                # the started signal so listeners don't see a stale ON
                # state right after they asked for OFF.
                log.debug(
                    "rotation engine: _on_thread_started saw "
                    "_running=False (stop() raced ahead) — bailing")
                return
            self._timer = t
        t.start()
        # First tick fires on a short delay so engine has time to
        # initialize without blocking the UI
        QTimer.singleShot(self.BOOT_DELAY_MS, self._on_tick)
        self.started.emit()
        log.debug(f"rotation engine thread {QThread.currentThread()!r} ready")

    def _on_thread_finished(self) -> None:
        self.stopped.emit()

    def _on_tick(self) -> None:
        """Per-tick handler. Wrapped in try/except so a bad tick
        emits error_occurred but doesn't kill the engine — the next
        tick fires regardless."""
        if not self.is_enabled():
            self._set_state(STATE_OFF)
            return
        try:
            self.tick()
        except Exception as exc:
            self._set_state(STATE_ERROR)
            msg = f"tick failed: {type(exc).__name__}: {exc}"
            log.warning(msg)
            try:
                Settings().set(KEY_LAST_ERROR, msg)
            except Exception:
                pass
            try:
                self.error_occurred.emit(msg)
            except Exception:
                pass

    # ── Public algorithm — pure functions ─────────────────────────────

    def compute_weight(self, *,
                         song_id: int,
                         song_category_id: Optional[int],
                         song_artist: Optional[str],
                         primary_category_id: int,
                         hour: int,
                         now: Optional[datetime] = None) -> float:
        """Pure Time-Slot Freshness weight for one song.

        Returns 0 when the song must NOT be picked (vetoed) — caller
        skips. Returns a positive weight for use in weighted random
        choice.

        ``primary_category_id`` is the clock's primary category — used
        for the ×1.2 boost when the song belongs to it. Sister-pool
        membership has been resolved by the caller already (the song
        is already in the candidate list)."""
        now = now or datetime.now()
        h = int(hour)
        if h < 0 or h > 23:
            raise ValueError(f"hour must be 0-23, got {hour!r}")

        # ── 1. Slot freshness — when did this song last play in hour H?
        last_slot_iso = self._db.get_song_last_played_in_hour(int(song_id), h)
        if last_slot_iso is None:
            slot_weight = self.WEIGHT_NEVER
        else:
            try:
                last_slot_date = _date.fromisoformat(last_slot_iso)
                age_days = (now.date() - last_slot_date).days
            except (ValueError, TypeError):
                age_days = 999    # malformed → treat as ancient
            if age_days < 0:
                age_days = 0
            slot_weight = self.SLOT_AGE_WEIGHTS.get(
                age_days, self.WEIGHT_DEFAULT)

        # ── 2. Primary boost — only when the clock has a REAL primary
        # category (NULL/0 = "All Songs" slot → uniform ×1.0, no boost)
        pri = int(primary_category_id or 0)
        boost = (self.PRIMARY_BOOST
                 if pri > 0 and int(song_category_id or -1) == pri
                 else 1.0)
        weight = slot_weight * boost

        # ── 3. Overall recency vetoes
        if weight > 0:
            # 4-hour same-song rule
            last_overall = self._db.get_song_last_played_at(int(song_id))
            if last_overall:
                try:
                    last_dt = datetime.fromisoformat(last_overall)
                    hours_since = (now - last_dt).total_seconds() / 3600.0
                    if hours_since < self.OVERALL_RECENT_HRS:
                        return 0.0
                except (ValueError, TypeError):
                    pass
            # 1-hour same-artist rule
            if song_artist:
                artist_iso = self._db.get_artist_last_played_at(
                    str(song_artist))
                if artist_iso:
                    try:
                        artist_dt = datetime.fromisoformat(artist_iso)
                        hrs = (now - artist_dt).total_seconds() / 3600.0
                        if hrs < self.OVERALL_ARTIST_HRS:
                            return 0.0
                    except (ValueError, TypeError):
                        pass
        return float(weight)

    def explain_weight(self, *,
                         song_id: int,
                         song_category_id: Optional[int],
                         song_artist: Optional[str],
                         primary_category_id: int,
                         hour: int,
                         now: Optional[datetime] = None) -> dict:
        """Like ``compute_weight`` but returns a structured breakdown:

            {
              'weight':         final weight,
              'slot_age_days':  int or None,
              'slot_weight':    pre-boost weight from curve,
              'boost':          1.0 or 1.2,
              'veto_reason':    str or None,
            }

        Used by the UI to render the AI Reasoning strip on each clock
        card in the Daily Plan Review screen. Same math as
        compute_weight — single source of truth."""
        now = now or datetime.now()
        h = int(hour)
        out = {
            "weight":        0.0,
            "slot_age_days": None,
            "slot_weight":   0.0,
            "boost":         1.0,
            "veto_reason":   None,
        }

        last_slot_iso = self._db.get_song_last_played_in_hour(
            int(song_id), h)
        if last_slot_iso is None:
            out["slot_weight"] = self.WEIGHT_NEVER
        else:
            try:
                last_slot_date = _date.fromisoformat(last_slot_iso)
                age = (now.date() - last_slot_date).days
                out["slot_age_days"] = age
                out["slot_weight"] = self.SLOT_AGE_WEIGHTS.get(
                    max(0, age), self.WEIGHT_DEFAULT)
            except (ValueError, TypeError):
                out["slot_weight"] = self.WEIGHT_DEFAULT

        pri = int(primary_category_id or 0)
        boost = (self.PRIMARY_BOOST
                 if pri > 0 and int(song_category_id or -1) == pri
                 else 1.0)
        out["boost"] = boost
        out["weight"] = out["slot_weight"] * boost

        if out["weight"] > 0:
            last_overall = self._db.get_song_last_played_at(int(song_id))
            if last_overall:
                try:
                    last_dt = datetime.fromisoformat(last_overall)
                    hours_since = (now - last_dt).total_seconds() / 3600.0
                    if hours_since < self.OVERALL_RECENT_HRS:
                        out["veto_reason"] = (
                            f"played {hours_since:.1f}h ago (<4h rule)")
                        out["weight"] = 0.0
                        return out
                except (ValueError, TypeError):
                    pass
            if song_artist:
                artist_iso = self._db.get_artist_last_played_at(
                    str(song_artist))
                if artist_iso:
                    try:
                        artist_dt = datetime.fromisoformat(artist_iso)
                        hrs = (now - artist_dt).total_seconds() / 3600.0
                        if hrs < self.OVERALL_ARTIST_HRS:
                            out["veto_reason"] = (
                                f"artist played {hrs:.1f}h ago (<1h rule)")
                            out["weight"] = 0.0
                            return out
                    except (ValueError, TypeError):
                        pass
        return out

    def candidate_pool(self, primary_category_id) -> list:
        """Return enabled songs in the sister-pool of the given
        primary category. Pool = {primary} ∪ sisters.

        A NULL/0 primary category means an "All Songs" slot (the
        operator's real on-air clocks use this) — the pool is the
        whole enabled library instead of disabling the feature."""
        pid = int(primary_category_id or 0)
        if pid <= 0:
            return self._db.get_all_enabled_songs()
        pool_ids = self._db.get_sister_pool_for_category(pid)
        return self._db.get_songs_in_categories(pool_ids)

    def pick_song_for_clock(self, *,
                              clock_id: int,
                              hour: int,
                              primary_category_id: int,
                              now: Optional[datetime] = None
                              ) -> Optional[dict]:
        """Weighted-random song pick for a (clock, hour). This is the
        function Phase E will hook into SchedulerEngine.pick_next_item
        to drive live broadcast.

        Algorithm:
          1. Get sister pool for primary_category_id
          2. Fetch all enabled songs in pool (real on-disk file)
          3. Compute weight for each (Time-Slot Freshness)
          4. Filter out weight=0 candidates (vetoed)
          5. Weighted-random pick

        Falls back to None if pool is empty or all vetoed —
        SchedulerEngine then reverts to its native random+separation
        pick (operator's Q4 = (b) safety fallback)."""
        now = now or datetime.now()
        primary = int(primary_category_id or 0)
        songs = self.candidate_pool(primary)
        if not songs:
            return None
        if primary <= 0:
            log.info(
                f"[rotation-ai] pick_song_for_clock clock={clock_id} "
                f"hour={hour}: NULL/0 category — all-songs pool "
                f"({len(songs)} candidates)")
        weights: list[float] = []
        eligible: list[dict] = []
        for s in songs:
            w = self.compute_weight(
                song_id=int(s["id"]),
                song_category_id=s.get("category_id"),
                song_artist=s.get("artist"),
                primary_category_id=primary,
                hour=int(hour),
                now=now)
            if w > 0:
                weights.append(w)
                eligible.append(s)
        if not eligible:
            return None
        pick = self._rng.choices(eligible, weights=weights, k=1)[0]
        return pick

    # ── Plan computation (engine writes decisions) ────────────────────

    def tick(self) -> Optional[int]:
        """One pass — pre-compute today's plan. Writes/updates the
        ai_rotation_plans row + flush of ai_rotation_decisions. Returns
        plan_id or None if no plan was computed (engine disabled, no
        active clocks today)."""
        plan_date = _date.today().isoformat()
        plan_id = self.compute_plan_for_date(plan_date)
        try:
            Settings().set(KEY_LAST_TICK_AT,
                            datetime.now().isoformat(timespec="seconds"))
            Settings().set(KEY_LAST_PLAN_DATE, plan_date)
            Settings().set(KEY_LAST_ERROR, "")
        except Exception:
            pass
        # Daily maintenance — 14-day retention purge of old plan
        # envelopes (+ CASCADE decisions). Sentinel-guarded so it runs
        # once per day; a purge failure must never kill the tick.
        try:
            last_purge = (Settings().get(KEY_LAST_PURGE_DATE, "")
                          or "").strip()
            if last_purge != plan_date:
                purged = self._db.purge_old_rotation_decisions()
                Settings().set(KEY_LAST_PURGE_DATE, plan_date)
                if purged:
                    log.info(
                        f"[rotation-ai] retention purge removed "
                        f"{purged} plan(s) older than 14 days")
        except Exception as exc:
            log.warning(f"[rotation-ai] retention purge failed: {exc}")
        self._set_state(STATE_ON)
        plan = self._db.get_ai_rotation_plan(plan_date)
        summary = {
            "plan_date": plan_date,
            "rested":    int(plan.get("rested_count", 0)) if plan else 0,
            "promoted":  int(plan.get("promoted_count", 0)) if plan else 0,
            "balanced":  int(plan.get("clocks_balanced", 0)) if plan else 0,
        }
        try:
            self.tick_completed.emit(int(plan_id), summary)
        except Exception:
            pass
        log.info(
            f"[rotation-ai] tick complete plan_id={plan_id} "
            f"rested={summary['rested']} "
            f"promoted={summary['promoted']} "
            f"balanced={summary['balanced']}")
        return plan_id

    def compute_plan_for_date(self, plan_date: str) -> int:
        """Walk every (clock, hour) cell in auto_schedule for the
        weekday of plan_date. For each clock's rotation-eligible song
        slot, simulate the AI pick + flag rest decisions. Persist to
        ai_rotation_decisions. Returns plan_id.

        Operator decisions are authoritative: if today's plan has
        already been approved / auto-applied / discarded, the plan and
        its decisions are left untouched (recomputing would silently
        wipe the operator's call — BUG-1). Only a 'pending' (or
        absent) plan is reset + recomputed."""
        existing = self._db.get_ai_rotation_plan(plan_date)
        if existing and (str(existing.get("status") or "").lower()
                          in ("approved", "auto_applied", "discarded")):
            log.info(
                f"[rotation-ai] compute_plan {plan_date}: plan already "
                f"'{existing['status']}' — preserving operator "
                f"decision, skipping recompute")
            return int(existing["id"])
        # Wipe + reset the day's plan envelope
        plan_id = self._db.reset_ai_rotation_plan(plan_date)
        target_day = _date.fromisoformat(plan_date)
        weekday = target_day.weekday()
        # Sim time = noon of plan_date (predictable for tests)
        sim_now = datetime.combine(
            target_day, datetime.min.time()).replace(hour=12)

        grid = self._db.get_auto_schedule_grid()
        # Filter cells for the target weekday
        cells = sorted(
            [(h, cid) for (d, h), cid in grid.items() if d == weekday],
            key=lambda x: x[0])
        if not cells:
            log.info(
                f"[rotation-ai] compute_plan {plan_date}: no auto_schedule "
                f"cells for weekday {weekday}")
            return plan_id

        rested = 0
        promoted = 0
        clocks_touched: set = set()
        all_songs_slots = 0
        # Dedupe guard — one 'rest' row per (clock, hour, song) even
        # when a clock has several song slots sharing the same pool
        # (BUG: rested_count was inflated once per song-slot).
        rest_seen: set = set()

        for hour, clock_id in cells:
            try:
                slots = self._db.get_clock_slots(int(clock_id))
            except Exception as exc:
                log.warning(
                    f"[rotation-ai] get_clock_slots({clock_id}) failed: {exc}")
                continue
            if not slots:
                continue

            for slot in slots:
                slot_dict = self._slot_to_dict(slot)
                # Only rotation-eligible song slots
                if (slot_dict.get("slot_type", "").lower() != "song"):
                    continue
                # NULL/0 category = "All Songs" slot — the operator's
                # real on-air clocks use this. Instead of skipping
                # (which left plans with 0 decisions), run the
                # algorithm over the whole enabled library with no
                # primary boost (primary_category_id=0 sentinel).
                cat_id = slot_dict.get("category_id")
                primary_cat = int(cat_id) if cat_id else 0
                if primary_cat < 0:
                    primary_cat = 0
                # Skip specific-song / specific-artist slots — operator
                # pinned those explicitly, AI must not override
                if (slot_dict.get("specific_song_id")
                        or slot_dict.get("specific_artist_id")):
                    continue
                if primary_cat == 0:
                    all_songs_slots += 1
                # Compute decisions for this (clock, hour, primary_cat)
                slot_idx = int(slot_dict.get("slot_order") or 0)
                r, p = self._decide_for_slot(
                    plan_id=plan_id,
                    plan_date=plan_date,
                    clock_id=int(clock_id),
                    hour=int(hour),
                    slot_idx=slot_idx,
                    primary_category_id=primary_cat,
                    sim_now=sim_now,
                    rest_seen=rest_seen,
                )
                rested += r
                promoted += p
                if r > 0 or p > 0:
                    clocks_touched.add(int(clock_id))

        if all_songs_slots:
            log.info(
                f"[rotation-ai] compute_plan {plan_date}: "
                f"{all_songs_slots} slot(s) had NULL/0 category — "
                f"used all-songs candidate pool (no primary boost)")

        self._db.update_ai_rotation_plan_stats(
            plan_id, rested=rested, promoted=promoted,
            clocks_balanced=len(clocks_touched), errors=0)
        return plan_id

    def _decide_for_slot(self, *,
                           plan_id: int,
                           plan_date: str,
                           clock_id: int,
                           hour: int,
                           slot_idx: int,
                           primary_category_id: int,
                           sim_now: datetime,
                           rest_seen: Optional[set] = None) -> tuple:
        """Run the algorithm once for one (clock, hour, primary) tuple.
        Writes rest + pick decisions to the DB. Returns
        ``(rested_count, promoted_count)`` so the plan envelope's
        aggregate counters stay accurate.

        ``primary_category_id`` = 0 means an "All Songs" slot — pool
        is the whole enabled library, no primary boost, and the pick
        is always action='pick' (there is no sister/promote notion).

        ``rest_seen`` is a caller-owned set of (clock_id, hour,
        song_id) tuples — a song is rested at most ONCE per (clock,
        hour) even when the clock has several song slots sharing the
        same pool, so rested_count counts unique songs."""
        all_songs = int(primary_category_id or 0) <= 0
        songs = self.candidate_pool(primary_category_id)
        if not songs:
            return (0, 0)
        if rest_seen is None:
            rest_seen = set()

        # Split pool into primary vs sister + score everything.
        # All-songs mode: every song counts as primary (no sisters).
        primary_songs: list[tuple[dict, float, dict]] = []
        sister_songs:  list[tuple[dict, float, dict]] = []
        for s in songs:
            explain = self.explain_weight(
                song_id=int(s["id"]),
                song_category_id=s.get("category_id"),
                song_artist=s.get("artist"),
                primary_category_id=primary_category_id,
                hour=hour, now=sim_now)
            triple = (s, explain["weight"], explain)
            if (all_songs
                    or int(s.get("category_id") or -1)
                        == primary_category_id):
                primary_songs.append(triple)
            else:
                sister_songs.append(triple)

        # Rest decisions — primary songs with weight=0 (these would
        # have been picked by random+separation, AI vetoed)
        rested_count = 0
        for s, w, ex in primary_songs:
            if w == 0.0:
                key = (int(clock_id), int(hour), int(s["id"]))
                if key in rest_seen:
                    continue    # already rested for this (clock, hour)
                rest_seen.add(key)
                reason = self._rest_reason(ex)
                if all_songs:
                    # song's own category (may be NULL) — 0 is not a
                    # valid categories(id) FK value
                    song_cat = s.get("category_id")
                    src_cat = int(song_cat) if song_cat else None
                else:
                    src_cat = primary_category_id
                self._db.add_rotation_decision(
                    plan_id=plan_id, decision_date=plan_date,
                    clock_id=clock_id, hour=hour, slot_idx=slot_idx,
                    song_id=int(s["id"]),
                    action="rest",
                    source_category_id=src_cat,
                    target_category_id=None,
                    reason=reason)
                rested_count += 1

        # Pick decision — weighted random from eligible (any source)
        eligible = [(s, w) for s, w, _ in primary_songs + sister_songs
                     if w > 0]
        if not eligible:
            return (rested_count, 0)
        pick = self._rng.choices(
            [t[0] for t in eligible],
            weights=[t[1] for t in eligible], k=1)[0]
        pick_cat = int(pick.get("category_id") or 0)
        if all_songs:
            action = "pick"
        else:
            action = ("promote" if pick_cat != primary_category_id
                      else "pick")
        promoted_count = 1 if action == "promote" else 0
        # Reason — find this song's explain block
        pick_explain = next(
            (ex for s, _, ex in primary_songs + sister_songs
             if int(s["id"]) == int(pick["id"])), {})
        reason = self._pick_reason(pick, pick_explain, primary_category_id)
        self._db.add_rotation_decision(
            plan_id=plan_id, decision_date=plan_date,
            clock_id=clock_id, hour=hour, slot_idx=slot_idx,
            song_id=int(pick["id"]),
            action=action,
            source_category_id=(pick_cat if pick_cat > 0 else None),
            target_category_id=(None if all_songs
                                 else primary_category_id),
            reason=reason)
        return (rested_count, promoted_count)

    # ── Reason / explain builders ─────────────────────────────────────

    @staticmethod
    def _rest_reason(explain: dict) -> str:
        if explain.get("veto_reason"):
            return explain["veto_reason"]
        age = explain.get("slot_age_days")
        if age == 0:
            return "slot_age=0 — played today at this hour"
        if age == 1:
            return "slot_age=1 — played yesterday at this hour"
        return f"slot_weight=0 (slot_age={age})"

    @staticmethod
    def _pick_reason(song: dict, explain: dict,
                       primary_category_id: int) -> str:
        cat = int(song.get("category_id") or 0)
        age = explain.get("slot_age_days")
        boost = explain.get("boost", 1.0)
        if int(primary_category_id or 0) <= 0:
            origin = "all songs"
        elif cat != primary_category_id:
            origin = "sister category"
        else:
            origin = "primary"
        if age is None:
            return f"from {origin} · slot_age=never · weight=1.30"
        return (f"from {origin} · slot_age={age}d · "
                f"boost=×{boost:.1f}")

    # ── Internal helpers ──────────────────────────────────────────────

    @staticmethod
    def _slot_to_dict(slot) -> dict:
        """sqlite3.Row → plain dict so .get() works."""
        try:
            return {k: slot[k] for k in slot.keys()}
        except (TypeError, AttributeError):
            return ({k: slot[k] for k in slot.keys()}
                    if isinstance(slot, dict) else {})

    def _set_state(self, new_state: str) -> None:
        if new_state == self._state:
            return
        self._state = new_state
        try:
            self.engine_state_changed.emit(new_state)
        except Exception:
            pass
