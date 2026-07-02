# Rotation AI — Consumption Path Audit (scheduler side)

Audit date: 2026-07-02 · READ-ONLY audit, no code or DB changes.
Scope: how `SchedulerEngine._pick_song` consumes `RotationAIEngine` decisions on air.

## How the consult actually flows (walkthrough, file:line)

1. **Wiring** — `ui/main_window.py:114-115` instantiates ONE `RotationAIEngine`;
   `ui/main_window.py:675` calls `self._scheduler.set_rotation_engine(self._rotation_engine)`
   (`core/scheduler/engine.py:156-159` stores the raw handle in `self._rotation_engine`).
   `ui/main_window.py:680` then starts the engine (own QThread + hourly QTimer,
   `core/rotation_ai_engine.py:109` `TICK_INTERVAL_MS = 3_600_000`).

2. **Per-pick context** — `pick_next_item` stashes `_current_pick_clock_id / _current_pick_hour /
   _current_pick_now` before walking slots (`core/scheduler/engine.py:526-530`), so `_pick_song`
   can consult without a signature change.

3. **Consult gate** — `core/scheduler/engine.py:740-773` (step "3.5" of `_pick_song`). Fires only when
   ALL of:
   - slot has no `specific_song_id` / `specific_artist_id` (early-returned at 711-732 — operator pins win),
   - slot `filter_json` produced no candidates (`not songs`, line 749 — filter wins when it matches),
   - slot has a `category_id` (line 749),
   - `self._rotation_engine is not None` (line 750),
   - `rotation_engine.is_enabled()` — Settings key `rotation_ai_engine_enabled` (line 752;
     `core/rotation_ai_engine.py:145-150`),
   - today's `ai_rotation_plans` row exists AND `status in ("approved", "auto_applied")`
     (lines 754-757; `today = date.today().isoformat()`).

4. **The consult itself** — `rotation_engine.pick_song_for_clock(clock_id, hour, primary_category_id, now)`
   (`core/rotation_ai_engine.py:431-471`). CRUCIALLY, this does **not read `ai_rotation_decisions` at all** —
   it re-runs the Time-Slot-Freshness algorithm live: `candidate_pool()` (sister pool via
   `core/database.py:1558-1577` + `get_songs_in_categories` 1802-1823), then per-song
   `compute_weight()` (rotation_ai_engine.py:276-343 — 1-3 DB queries per song), then
   `self._rng.choices(eligible, weights=…)` (line 470). Returns a full song dict or `None`.
   The `clock_id` parameter is accepted but **never used** in the algorithm body.

5. **Scheduler use of the pick** — on a non-None return, `_pick_song` logs one INFO line and
   returns `self._song_row_to_item(ai_pick)` immediately (engine.py:763-769). No re-validation,
   no separation check, no decision-row write-back.

6. **Fallback** — `ai_pick is None` or any exception falls through (`except` at 770-773, log at
   DEBUG only) to step 4: legacy `get_songs(category_id…)` (776-788) → `fallback_category_id`
   (791-799) → any song (800-804) → separation filter + `random.choice` (808-815).

7. **Approval lifecycle** — Daily Plan Review approve → `mark_ai_rotation_plan_approved`
   (main_window.py:1245, database.py:1690-1701); discard → status='discarded' + decisions wiped
   (database.py:1703-1722); 5 PM auto-apply safety net → `_check_ai_rotation_auto_apply`
   (main_window.py:1286-1333, 60s QTimer, idempotent via Settings sentinel
   `last_rotation_auto_apply_date`).

## 🐛 Bugs found

### BUG 1 — CRITICAL: hourly engine tick silently un-approves the plan; consult window is ≤1 hour per day
- `RotationAIEngine.tick()` (rotation_ai_engine.py:475-481) runs **every hour** (TICK_INTERVAL_MS=3.6M ms,
  line 109) and unconditionally calls `compute_plan_for_date(today)` → `reset_ai_rotation_plan`
  (rotation_ai_engine.py:514).
- `reset_ai_rotation_plan` (core/database.py:1601-1619) **wipes all decisions AND resets
  `status='pending'`, `approved_at=NULL`** — with no guard for an already-approved/auto_applied plan.
- The scheduler's consult gate requires `status in ("approved","auto_applied")` (engine.py:756-757).
- Net effect on air: operator approves at 10:07 → consult is live until the ~11:00 tick → status flips
  back to 'pending' → **AI consult silently stops firing; fallback random+separation takes over for the
  rest of the day.** The 5 PM auto-apply fires once (pending→auto_applied) but the ~6 PM tick reverts it
  and the sentinel (`stamped == today`, main_window.py:1305) blocks re-application. Manual Refresh
  (`_on_sched_ai_refresh`, main_window.py:1137-1151) triggers the same reset.
- Result: the USP feature is effectively active for at most ~1 hour after each approval. The rest of the
  time an "approved" plan changes nothing on air. No log line marks the demotion (the tick log at
  rotation_ai_engine.py:501-505 doesn't mention status).
- Fix direction (not applied): `tick()` should skip recompute when today's plan status is
  approved/auto_applied, or `reset_ai_rotation_plan` must preserve a non-pending status.

### BUG 2 — MAJOR: approved decisions are never consumed; live pick re-rolls the dice
- `pick_song_for_clock` (rotation_ai_engine.py:431-471) never reads `ai_rotation_decisions`. What the
  operator reviewed/approved in Daily Plan Review (written by `_decide_for_slot`,
  rotation_ai_engine.py:580-652, computed with `sim_now = noon` of plan date, line 517-519) is a
  **preview only**. The on-air pick recomputes weights with live `now` and a fresh
  `self._rng.choices` roll — so the aired song routinely differs from the approved "pick"/"promote"
  decision row for that (clock, hour, slot).
- Rest decisions *mostly* coincide (weight=0 recomputes the same way), but overall-recency vetoes
  (4h/1h) computed at sim-noon vs live time diverge.
- On-air impact: "approve" governs *whether* the algorithm runs (gate), not *what* was approved.
  Rotation Health audits the planned decisions, not what actually aired — the evidence trail cannot
  detect divergence.

### BUG 3 — MAJOR: REST decisions do not constrain the fallback ladder — plan is advisory-only
- When the consult is skipped (plan pending — nearly always, per BUG 1; engine disabled; sister pool
  empty; all candidates vetoed → `pick_song_for_clock` returns None at rotation_ai_engine.py:468-469),
  `_pick_song` falls to `random.choice` over `get_songs(category_id…)` (engine.py:776-815).
- That ladder filters only by 240-min same-song / 60-min same-artist windows
  (`SEPARATION_SAME_SONG_MIN=240`, `SEPARATION_SAME_ARTIST_MIN=60`, engine.py:469-470;
  `_recent_song_ids/_recent_artists` engine.py:1207-1237). It never reads `ai_rotation_decisions`.
- A song the AI "rested" (e.g. slot_age=0, played today at this hour, 5 hours ago) passes the 4-hour
  separation and can air again via `random.choice` — exactly what the rest decision was supposed to
  prevent. Worse, engine.py:815 `random.choice(songs)` deliberately ignores even the separation filter
  when it empties the pool.
- Combined with BUG 1: for most of the broadcast day the AI plan is cosmetic.

### BUG 4 — MEDIUM: consult failure is invisible in production
- The whole consult is wrapped in `except Exception` logged at **DEBUG** (engine.py:770-773). In normal
  (non `--debug`) operation a permanently broken consult (schema drift, bad plan row, engine exception)
  is indistinguishable from "no plan approved". No `error_occurred` emission, no counter. Also no INFO
  log when the gate simply doesn't pass, so BUG 1 is undetectable from logs.

### BUG 5 — MEDIUM: cross-thread `tick()` race can interleave plan writes
- The engine's QTimer tick runs on the rotation QThread (rotation_ai_engine.py:228-246), but MainWindow's
  Refresh button calls `self._rotation_engine.tick()` **synchronously on the UI thread**
  (main_window.py:1141-1144). Two threads can concurrently run
  `reset_ai_rotation_plan` + `add_rotation_decision` loops against the same plan_id (thread-local
  connections, database.py:36-44, so no shared-cursor crash, but interleaved DELETE/INSERT can yield a
  mixed plan: half old-tick decisions, half new). Also blocks the UI for the full plan computation
  (hundreds–thousands of queries).

### BUG 6 — LOW: `peek_next` consults with a mismatched date/hour context
- The consult always looks up the plan for `date.today()` (engine.py:753-755) but computes weights with
  `self._current_pick_now` (line 762), which callers may set to a future/simulated `now`
  (`pick_next_item(now=…)`, peek paths). A peek across midnight consults today's plan for tomorrow's
  hours. Low impact live (Studio passes real now), but tests/simulations diverge.
- Related nit: `_current_pick_now` is only created inside `pick_next_item` (engine.py:530), never in
  `__init__` (only clock_id/hour are, engine.py:153-154) — calling `_pick_song` directly (as
  tests/test_rotation_pickers.py does) relies on the consult gate short-circuiting before line 762, else
  `AttributeError` (currently swallowed by the DEBUG except).

### BUG 7 — LOW: no on-disk validation of the AI pick (shared with fallback ladder)
- `get_songs_in_categories` guarantees `is_enabled=1` and non-empty `file_path`
  (database.py:1812-1821) but nothing checks the file exists. `_pick_song` hard-returns the AI pick
  (engine.py:769). A rested/promoted song whose file was deleted keeps its high freshness weight
  (it never logs a play → `WEIGHT_NEVER=1.30` boost) so weighted-random will *re-favour* the broken
  song on retries — repeated dead picks in a small sister pool. Not an infinite loop (dispatch skips
  onward), and the fallback ladder has the same gap, but the AI weighting makes it stickier.

## ⚠ Design risks

1. **Per-pick query storm** — `pick_song_for_clock` issues up to 3 queries per candidate
   (`get_song_last_played_in_hour` database.py:1866-1890, `get_song_last_played_at` 1825-1835,
   `get_artist_last_played_at` 1851-1864). A sister pool of ~300 songs (395-song library) ≈ 600-900
   queries per pick. `peek_next(n=5)` (engine.py:625-674) simulates 5 dispatches → up to ~4,500 queries
   per queue refresh, re-triggered on every `queue_changed`. Each query is index-backed
   (`idx_broadcast_song ON broadcast_log(song_id, played_at)` schema.sql:530; artist via
   `idx_songs_artist` 518) so individually sub-ms, but as `broadcast_log` grows this is the hottest path
   in the app and runs on the 1 Hz scheduler thread. The `CAST(strftime('%H',…))` predicate
   (database.py:1884) scans each song's full history slice. No caching, no bulk variant
   (a bulk `get_last_played_map` exists at database.py:1837 but isn't used here).
   Note: `ai_rotation_decisions` indexes (schema.sql:690-697) are irrelevant to the consult —
   the consult never queries that table (BUG 2).

2. **Threading of the consult call** — scheduler QThread directly invokes methods on a QObject living on
   the rotation QThread (engine.py:758). The invoked path is pure Python + DB (no Qt signals/widgets), DB
   uses thread-local connections (database.py:29, 36-44), and `Settings()` is a cached singleton — so
   no Qt-affinity violation today. But `self._rng` (`random.Random`, rotation_ai_engine.py:134) is
   shared between the scheduler-thread consult and the engine-thread `_decide_for_slot` — GIL-safe in
   practice, non-deterministic under contention. Fragile contract: any future addition of a signal emit
   or QTimer inside `pick_song_for_clock` becomes a cross-thread Qt bug.

3. **peek vs dispatch divergence** — because the consult is weighted-random with no decision pinning,
   the "Up Coming" preview (peek) and the real dispatch roll independently; the queue shown to the
   operator will not match what airs. Inherent to re-rolling (BUG 2) rather than consuming pinned
   decisions.

4. **`clock_id` accepted but unused** by `pick_song_for_clock` (rotation_ai_engine.py:431-471) —
   intentional per operator decision D2 (hour-of-day slot, weekday-agnostic), but the signature implies
   per-clock behaviour that doesn't exist; logged pick lines (engine.py:764-768) imply clock-specific AI.

## Answers to checklist (condensed)

1. Consult only when today's plan status ∈ {approved, auto_applied} (engine.py:756-757). Pending and
   discarded correctly skip. Stale yesterday plan cannot leak (lookup keyed to `date.today()`), BUT the
   approved status itself is destroyed hourly (BUG 1).
2. Returns a full song row (id/title/artist/file_path/duration). Scheduler hard-uses it — no re-check of
   enabled/deleted/on-disk (SQL pre-filters enabled + non-empty path; no disk check — BUG 7).
3. AI-None / exception → falls to the normal ladder (category → fallback_category → any song). No
   dead-end (engine.py:770-806). ✔
4. No — rest decisions bind ONLY inside the consult recomputation. Fallback random can air rested songs
   (BUG 3).
5. No conflict — the promoted sister song is returned as-is; `_pick_song` returns before any category
   re-filter (engine.py:769). ✔
6. AI pick bypasses the scheduler's separation filter entirely, but `compute_weight` enforces the same
   4h-song/1h-artist vetoes internally (rotation_ai_engine.py:105-106, 319-342) — numerically identical
   to SEPARATION_SAME_SONG_MIN=240/ARTIST=60. No fight; single-sourceable but currently duplicated
   constants in two files.
7. `is_enabled()` checked per pick (engine.py:752) — full skip when '0', no half-state. Also the engine's
   own `_on_tick` no-ops when disabled (rotation_ai_engine.py:256-258). ✔
8. Direct cross-thread Python call; safe today (thread-local DB conns, no Qt in the path) — see Design
   risk 2. UI-thread `tick()` via Refresh is the real race (BUG 5).
9. Up to 3 index-backed queries × pool size per consult; peek_next(5) multiplies ×5 — see Design risk 1.
10. Evidence = one `log.info` line (engine.py:764-768) only. No write-back: decision rows have no
    applied/played status update, `broadcast_log` rows aren't tagged as AI-picked, and Rotation Health
    renders the *planned* decisions — actual-vs-planned divergence is unauditable (BUG 2 corollary).
11. See below.

## Test coverage gaps

`tests/test_rotation_pickers.py` (279 lines) contains **zero rotation-AI consult tests** — no test ever
calls `set_rotation_engine`; the consult gate is dormant in every case (also why BUG 6's uninitialized
`_current_pick_now` never surfaces). It covers jingle/sweeper/station-id/voice-track/break pickers,
separation helpers, force-clock override, and mixed-slot dispatch only.

`tests/test_rotation_ai_engine.py` tests `pick_song_for_clock` in isolation (weighted pick + vetoes,
lines 443-511) and `tests/test_rotation_db.py` tests status stamping (approve 381-384, auto-apply
409-418) — but nothing spans the two layers.

Untested consult behaviours:
- Gate matrix: pending / discarded / approved / auto_applied / missing plan × enabled flag → does
  `_pick_song` consult or not (would pin BUG 1's contract).
- **Status survives a tick**: approve → `tick()` → status still approved (would have caught BUG 1).
- AI pick flows through `_pick_song` → item shape, sister-category promote accepted.
- AI returns None → fallback ladder engaged (no dead-end).
- Consult raises → fallback engaged + surfaced.
- Rested song excluded (or not) from fallback path — documents BUG 3 as intended/not.
- Operator-pin precedence (specific_song / specific_artist / filter_json beats consult).
- peek_next with consult active (query volume / no decision writes / cursor restore).
- Aired-pick equals approved decision row (would pin BUG 2's contract if pinning is ever intended).
