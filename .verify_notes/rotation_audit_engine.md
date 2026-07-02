# Rotation AI — Engine Algorithm Audit

Audit date: 2026-07-02 · READ-ONLY · Scope: `core/rotation_ai_engine.py`, 5-PM auto-apply in `ui/main_window.py`, `tests/test_rotation_ai_engine.py`, `tests/test_rotation_db.py`, plus the DB helpers in `core/database.py` and the scheduler consult in `core/scheduler/engine.py` they depend on.

## How it actually works (walkthrough)

**Weight math** — `RotationAIEngine.compute_weight()` (`core/rotation_ai_engine.py:276-343`):
1. `Database.get_song_last_played_in_hour(song_id, h)` (`core/database.py:1866-1890`) runs
   `SELECT MAX(DATE(played_at)) FROM broadcast_log WHERE song_id=? AND entry_type='song' AND CAST(strftime('%H', played_at) AS INT)=?`
   → returns a calendar DATE (YYYY-MM-DD), weekday-agnostic (no day-of-week filter).
2. `slot_age_days = (now.date() - last_slot_date).days` — pure **calendar-date diff**, clamped to ≥0 (`rotation_ai_engine.py:304-309`). Malformed date → 999 → default 1.00.
3. Ladder lookup via `SLOT_AGE_WEIGHTS` dict (`rotation_ai_engine.py:92-103`), `WEIGHT_DEFAULT=1.00` for 7+, `WEIGHT_NEVER=1.30` when the hour-H query returns None.
4. `PRIMARY_BOOST=1.20` when `song.category_id == primary_category_id` (`:313-317`).
5. Vetoes only evaluated when weight > 0 (`:319-342`): `get_song_last_played_at` (`database.py:1825`, MAX(played_at) anywhere) → `<4h` returns 0.0; `get_artist_last_played_at` (`database.py:1851`, exact `s.artist = ?` join) → `<1h` returns 0.0. Both use `(now - last_dt).total_seconds()/3600.0` — units correct.

**Pick** — `pick_song_for_clock()` (`:431-471`): pool = `get_sister_pool_for_category` (`database.py:1558`) ∪ self → `get_songs_in_categories` (enabled + non-empty file_path, `database.py:1802`) → compute weight per song → **candidates with w == 0 are filtered out before `random.choices`** (`:465-467`) → if none eligible, returns `None` (`:468-469`) so SchedulerEngine falls back to native random+separation. No ZeroDivision path exists.

**Daily plan** — `tick()` (`:475-506`) → `compute_plan_for_date(today)` (`:508-578`): `reset_ai_rotation_plan` wipes decisions + resets envelope to `pending` (`database.py:1601-1619`), walks the auto_schedule grid for the weekday (multi-hour ranges expanded per hour, `database.py:3315-3325`), for each rotation-eligible Song slot (category set, no specific_song/artist pin) calls `_decide_for_slot` (`:580-652`): writes `rest` decisions for weight-0 **primary** songs and one `pick`/`promote` decision from a weighted-random draw. Sim time is fixed at **noon of plan_date** (`:518-519`). Stats written to the envelope (`database.py:1661`). Settings sentinels `rotation_ai_last_tick_at`, `rotation_ai_last_plan_date`, `rotation_ai_last_error=""` stamped on success (`:483-486`).

**Runtime** — QThread + QTimer, tick every 3,600,000 ms (`:109`), first tick 5 s after boot (`:245`). `_on_tick` (`:252-272`) checks `is_enabled()` (Settings `rotation_ai_engine_enabled`, default ON, `:145-150`), wraps `tick()` in try/except → on error sets state ERROR, writes `rotation_ai_last_error`, emits `error_occurred`; engine and timer survive.

**Live consult** — `core/scheduler/engine.py:740-773`: scheduler consults AI only when engine set + slot has category + no filter/pins + `is_enabled()` + **today's plan status ∈ (approved, auto_applied)** — then calls `pick_song_for_clock()` **live**; the stored `ai_rotation_decisions` rows are never read at dispatch time (they drive UI screens only).

**5-PM auto-apply** — `ui/main_window.py:657-668` (60 s QTimer + a 3 s singleShot at boot) → `_check_ai_rotation_auto_apply` (`main_window.py:1286-1333`): after `now.hour >= 17`, if Settings sentinel `last_rotation_auto_apply_date != today` and plan exists and status == `pending` → `mark_ai_rotation_plan_auto_applied` (`database.py:1724`), stamp sentinel. Non-pending statuses stamp the sentinel and return (never overrides approve/discard). Fires once per day (sentinel), works for app launched after 5 PM (singleShot + first 60 s tick).

## Spec-vs-code compliance table

| Spec item | Code | Verdict | Evidence |
|---|---|---|---|
| today → 0.00 (hard veto) | `SLOT_AGE_WEIGHTS[0] = 0.00`, filtered out pre-choices | **MATCH** | rotation_ai_engine.py:93, :465 |
| yesterday → 0.05 | `SLOT_AGE_WEIGHTS[1] = 0.05` | **MATCH** | rotation_ai_engine.py:94 |
| 2d → 0.30 | `SLOT_AGE_WEIGHTS[2] = 0.30` | **MATCH** | rotation_ai_engine.py:95 |
| 3d → 0.60 | `SLOT_AGE_WEIGHTS[3] = 0.60` | **MATCH** | rotation_ai_engine.py:96 |
| 4d → 0.90 | `SLOT_AGE_WEIGHTS[4] = 0.90` | **MATCH** | rotation_ai_engine.py:97 |
| 5-6d → 1.00 | keys 5, 6 = 1.00 | **MATCH** | rotation_ai_engine.py:98-99 |
| 7+ → 1.00 | `WEIGHT_DEFAULT = 1.00` (dict-miss fallback) | **MATCH** | rotation_ai_engine.py:101, :310-311 |
| never-played → 1.30 | `WEIGHT_NEVER = 1.30` when never in hour H | **MATCH** (interpreted as never-in-hour-H — see risk R2) | rotation_ai_engine.py:102, :300-301 |
| "yesterday" = calendar day | `now.date() - DATE(played_at)` diff | **MATCH** (calendar semantics, not 24 h window) | rotation_ai_engine.py:304-305, database.py:1879 |
| primary_boost ×1.2 | `PRIMARY_BOOST = 1.20`, exact category-id equality | **MATCH** | rotation_ai_engine.py:103, :313-317 |
| <4 hr same-song veto | `hours_since < 4` → 0.0, timestamp diff in hours | **MATCH** | rotation_ai_engine.py:321-328 |
| <1 hr same-artist veto | `hrs < 1` → 0.0, but exact-string artist match | **MATCH w/ caveat** (case/whitespace — bug 4) | rotation_ai_engine.py:331-342, database.py:1860 |
| pick = random.choices(eligible, weights) | `self._rng.choices(eligible, weights=weights, k=1)` after zero-weight filter | **MATCH** | rotation_ai_engine.py:470 |
| Sister groups 2-5, symmetric | create validates 2 ≤ n ≤ 5; `UNIQUE(category_id)` = one group per category; pool returns full group for every member | **MATCH** | database.py:1365-1372, :1289, :1558-1577 |
| Statuses pending/approved/discarded/auto_applied | all four written; approved/auto_applied stamp `approved_at`; discard wipes decisions | **MATCH** | database.py:1690-1736 |
| 5-PM auto-apply if undecided | 60 s poll, `hour >= 17`, pending-only, date-keyed sentinel | **MATCH** | main_window.py:1286-1333 |
| Settings keys (4) | all four defined + written | **MATCH** | rotation_ai_engine.py:69-72, :483-486, :266 |
| Operator approval is authoritative | hourly tick **resets an approved plan to pending** | **MISMATCH** — bug 1 | rotation_ai_engine.py:514, database.py:1612-1617 |

## 🐛 Bugs found

**1. CRITICAL — Hourly tick silently un-approves the day's plan.**
`tick()` → `compute_plan_for_date()` → `reset_ai_rotation_plan()` unconditionally, every hour (`rotation_ai_engine.py:480-481, :514`; `database.py:1608-1617` sets `status='pending', approved_at=NULL` and deletes all decisions). There is no "already approved/auto_applied → skip" guard. On air this means:
- Operator approves at 10:00 → tick at ~10:05 (or next hourly tick) flips the plan back to `pending` → the scheduler's gate (`scheduler/engine.py:756-757` requires status approved/auto_applied) fails → **AI picking is disabled again within the hour**, with no UI indication.
- Worse after 5 PM: auto-apply fires at 17:00 and stamps the once-per-day sentinel (`main_window.py:1315-1318`); the next hourly tick resets status to `pending`; the sentinel prevents any re-apply — so the **entire evening broadcast runs without the rotation AI** despite the "safety net". The feature effectively only works for at most one hour per day.
No test covers approve-then-tick, which is why this survived.

**2. HIGH — Approved plan decisions are never what actually airs.**
The scheduler consults `pick_song_for_clock()` **live** (`scheduler/engine.py:758-762`) and never reads `ai_rotation_decisions`. The Daily Plan Review screen shows decisions computed at sim-noon (`rotation_ai_engine.py:518-519`), the operator "approves" those specific picks, but dispatch re-rolls a fresh weighted random with live `now`. The approval is really just an on/off gate. `main_window.py:1230-1233` even claims "Scheduler now treats today's decisions as authoritative" — it does not. Operators reviewing/approving specific songs are approving a simulation, not the broadcast. (Combined with bug 1, the decision rows shown in the UI are also wiped and re-rolled hourly, so the review screen's content churns.)

**3. MED — Manual Refresh runs a full plan compute on the UI thread, racing the worker tick.**
`_on_sched_ai_refresh` (`main_window.py:1141-1150`) calls `self._rotation_engine.tick()` directly — a plain synchronous call on the **main/UI thread**, while the engine's own QTimer tick runs on the worker QThread. Two consequences: (a) the UI freezes for the duration of a full grid walk (hundreds of weight queries against broadcast_log); (b) if the hourly tick fires concurrently, two threads interleave `reset_ai_rotation_plan` + `add_rotation_decision` on the same plan (no UNIQUE constraint on decisions, `database.py:1311-1327`) → duplicated/mixed decision rows or `database is locked` errors. Also `tick()` itself never checks `is_enabled()` (only `_on_tick` does, `:256-258`), so Refresh recomputes a plan even when the operator has turned the engine OFF.

**4. MED — Artist veto is exact-string, case- and whitespace-sensitive.**
`get_artist_last_played_at` uses `WHERE s.artist = ?` (`database.py:1860`). SQLite `=` on TEXT is case-sensitive: "Arijit Singh" vs "arijit singh" vs "Arijit Singh " are three different artists, so the 1-hour same-artist rule silently fails for library entries with inconsistent casing/trailing spaces — a realistic condition in a 395-song hand-tagged library. No `COLLATE NOCASE`, no `TRIM`. (Song-id-based 4-hour veto is unaffected.)

**5. MED — Yesterday's pending plan is never resolved, and `purge_old_rotation_decisions` is never called.**
At midnight the engine simply computes a new plan for the new date; yesterday's `pending` envelope + decisions stay forever. `purge_old_rotation_decisions` (`database.py:1786-1798`) — whose docstring says "Run by the engine's nightly maintenance tick" — has **zero production callers** (only a test calls it). `ai_rotation_plans`/`ai_rotation_decisions` grow unbounded on a 24/7 machine.

**6. LOW — Boot double-tick.**
`_on_thread_started` starts the interval timer *and* schedules a singleShot first tick (`rotation_ai_engine.py:242-245`). Combined with MainWindow's `QTimer.singleShot(3000, ...)` auto-apply probe and manual Refresh, multiple full recomputes can run close together at boot. Wasteful, and widens the bug-3 race window.

**7. LOW — Dead cache fields.**
`_cached_plan_date` / `_cached_plan_id` (`rotation_ai_engine.py:137-138`) are initialized, documented ("reset on day rollover or stop()") and never used anywhere. Misleading for maintainers.

**8. LOW — `start()` docstring promises an enable-gate that isn't there.**
`start()` says "No-op when operator has disabled the engine via Settings" (`:156-157`) but never checks `is_enabled()`; the thread+timer always spin up (each tick then early-exits). Harmless heartbeat, but the docstring lies and the state briefly shows WARMING even when OFF.

## ⚠ Design risks / ambiguities

- **R1 — Hour attribution is play-START hour only.** `broadcast_log.played_at` is stamped at insert time via `log_play` (`database.py:274-284`); the hour-H match is `strftime('%H', played_at) = H` (`database.py:1884`). A song starting 09:58 and playing into hour 10 counts **only for hour 9**. Deterministic and defensible, but the spec's "played in hour H" is ambiguous; listeners at 10:02 heard it, yet the 10:00 slot treats it as never-played-today.
- **R2 — "never-played" = never in hour H, not never anywhere.** A song played 300 times at other hours still gets the 1.30 boost for hour H (`rotation_ai_engine.py:300-301`) — the highest weight in the pool. That matches "Time-Slot Freshness" intent and the overall 4 h/1 h vetoes still guard it, but it means heavy-rotation songs outrank genuinely new songs in unfamiliar hours. Spec ambiguity resolved in a reasonable direction; worth an operator sign-off note.
- **R3 — Midnight edge is calendar-day, by design.** Played 23:59 yesterday → hour-23 slot_age=1 (0.05) at 00:01; played 00:01 today → hour-0 slot_age=0 (veto). Consistent with calendar-day spec; the <4 h overall veto covers the "minutes ago across midnight" hole. OK.
- **R4 — Timezone: consistent but fragile.** Production writes `datetime('now','localtime')` (`database.py:283`) and the engine compares with naive `datetime.now()` — consistent. But `MAX(played_at)` is a **lexicographic string max**: any future writer inserting `isoformat()` ("T" separator, as the tests do at `test_rotation_ai_engine.py:188`) alongside `datetime('now','localtime')` (space separator) corrupts MAX ordering, since `'T' > ' '`. One format drift away from wrong vetoes.
- **R5 — Sim-noon plan vs live picks.** Plan decisions computed at `sim_now=12:00` (`rotation_ai_engine.py:518-519`) ignore same-day intra-day history for morning hours and can't foresee evening plays; the 4 h/1 h vetoes evaluated at noon are meaningless for a 21:00 slot. Fine for a preview, another reason the plan diverges from dispatch (see bug 2).
- **R6 — Sister edge cases are safe.** A category can never be in two groups (`UNIQUE(category_id)`, `database.py:1289`); a sister category with 0 songs just contributes nothing (`get_songs_in_categories` returns fewer rows); ungrouped → pool of 1 (`database.py:1568-1569`). Groups auto-delete below 2 members (`database.py:1485-1487`).
- **R7 — Threading is sound overall.** Thread-local sqlite connections (`database.py:36-43`) make cross-thread DB use safe at the connection level; scheduler-thread calls into `pick_song_for_clock` and UI-thread `tick()` each get their own connection. Signals from the worker thread marshal via queued connections. Residual risks are the logical race in bug 3 and a shared `random.Random` across threads (`:134` — not thread-safe in theory, negligible in practice). `parent=self` at construction (`main_window.py:115-116`) is correctly detached via `setParent(None)` before `moveToThread` (`:165`).
- **R8 — Engine tests run against the live dev DB.** `tests/test_rotation_ai_engine.py` uses the `Database()` singleton (the real `%LOCALAPPDATA%` DB), writes today's plan and deletes `ai_rotation_plans WHERE plan_date = today` on teardown (`:157-160`) — running the suite while ON AIR wipes the live day's plan and churns Settings sentinels (the file's own Phase H comment at `:707-712` admits a prior leak). Do not run this suite on the broadcast machine during the day.

## Test coverage gaps

Covered well: ladder points 0/1/3/7+, never-boost, primary vs sister boost, both vetoes, bad-hour validation, explain breakdown, pool expansion, all-vetoed → None, plan write/reset idempotency, pin skipping, envelope stats, lifecycle idempotency, ERROR-state survival, disabled-tick skip, sentinels; DB-side: group constraints (min/max/dupe/cross-group/rollback/cap), status stamps, decision validation, purge, weekday-agnostic hour lookup.

Missing (each maps to a finding above):
1. **Approve → tick → status still approved** — would have caught bug 1 (CRITICAL). No test touches plan status after a recompute.
2. **5-PM auto-apply** — `_check_ai_rotation_auto_apply` has zero tests (grep `auto_apply` in tests/ → no hits): no test for pending→auto_applied, sentinel once-per-day, non-pending non-override, after-17:00 launch.
3. **Scheduler consult gating** — no test that the scheduler uses AI only when status approved/auto_applied + enabled, nor the fallback on `pick=None`.
4. Ladder buckets **2, 4, 5, 6 days** untested (only 0, 1, 3, 7 asserted) — an off-by-one in the dict would pass today's suite.
5. **Artist case/whitespace matching** untested (bug 4).
6. **Midnight/calendar-day edge** (23:59 vs 00:01) untested.
7. **Concurrent tick / Refresh reentrancy** untested (bug 3).
8. **Boundary veto values** — exactly 4.0 h / 1.0 h ago (strict `<` means eligible) untested.
9. **Mixed timestamp formats** in broadcast_log (R4) untested.
10. **compute_weight with disabled engine / tick() ignoring is_enabled** untested (bug 3, last point).
