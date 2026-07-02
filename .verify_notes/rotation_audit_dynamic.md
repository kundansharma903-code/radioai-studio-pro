# Rotation AI — Dynamic Behavior Probe

Date: 2026-07-02 · Target: `core/rotation_ai_engine.py` (RotationAIEngine, Time-Slot Freshness)

## Method (isolation approach used, proof live DB untouched)

- Live DB (`%LOCALAPPDATA%\RadioAI Studio Pro\Database\radioai.db`) was opened exactly once, **read-only** (`sqlite3.connect("file:...?mode=ro", uri=True)`), and snapshotted with the SQLite backup API to `%TEMP%\rotprobe\rotation_probe.db`. Live file size/mtime identical before and after the copy (1,191,936 bytes / mtime 1782967273.899). No writable handle to the live path was ever opened by any probe.
- Copy passed `PRAGMA quick_check` = ok (394 songs, 2,764 broadcast_log rows).
- Injection: `core/database.py` binds `DB_PATH` as a module global and connects lazily in `_conn()`, so every probe script did `import core.database as cdb; cdb.DB_PATH = <copy>` **before** instantiating `Database()`. Each experiment ran in a fresh `py` process (singleton isolation).
- Tamper-proofing: a `_probe_marker` table was created **on the copy only**; every script asserted the marker through the patched `Database()` connection before doing anything, guaranteeing all reads/writes hit the copy.
- Exception (sanctioned): Experiment 7 ran the project's own pytest suites, which use the live DB by design with cleanup fixtures.
- All temp scripts + the DB copy were deleted at the end (`%TEMP%\rotprobe\` removed).

## Experiment results

### 1. Full plan compute on the copy
- `compute_plan_for_date("2026-07-02")` (today, Thu) → plan_id created, **0 decisions**. Cause: `auto_schedule` only has cells for `day_of_week=5` (6 rows, hours 18–24).
- `compute_plan_for_date("2026-07-04")` (Saturday, the only populated day) → **still 0 decisions**. Cause: the on-air clock (id 3701 "New Clock") has 5 Song slots with `selection_mode='random_from_category'` but **`category_id=NULL` on every slot** — the engine skips slots where `cat_id is None` (`rotation_ai_engine.py:551-553`). Every historical plan in the DB (ids 372, 373, 418) also has rested=0/promoted=0 — the feature has never produced a single decision on this station.
- With a synthetic, correctly-configured clock (2 Song slots, real `category_id`, sister group A↔B) the engine produced 12 decisions (8 rest / 4 promote) and all correctness audits passed:
  - No false rests: every slot-age rest (`slot_age=0`) matched a real broadcast_log play at that hour; remaining rests carried `<4h` veto reasons and matched real recent plays.
  - All promotes were genuinely from sister categories of the primary.
  - No decisions referenced deleted / disabled / empty-file_path songs (pool query filters these).
  - No exact duplicate rows for the same clock+hour+slot; **but** the same song is rested once per song-slot (see Bug 3).

### 2. Weight function probe (`compute_weight` / `explain_weight`, fixed `now`=2026-07-02 12:00)
Expected vs observed — **every ladder value exact**:

| case | expected | observed |
|---|---|---|
| played today at hour | 0.00 | 0.00 |
| yesterday | 0.05 | 0.05 |
| 2d | 0.30 | 0.30 |
| 3d | 0.60 | 0.60 |
| 4d | 0.90 | 0.90 |
| 5d / 6d / 7d / 30d | 1.00 | 1.00 |
| never | 1.30 | 1.30 |
| never + primary boost | 1.56 (1.30×1.20) | 1.56 |

Midnight edge: play at 2026-07-01 23:59, queried at hour=23 with now=2026-07-02 00:01 → `slot_age_days=1`, slot bucket 0.05 (calendar-date bucketing flips correctly at midnight); final weight 0 anyway via the `<4h` overall veto (played 0.0h ago). Play at 00:01 today queried for hour 0 → slot_age 0 → 0.00. Bucketing behaves per spec.

### 3. Veto probe
- Song X played 3.5h before `now` → weight 0.0, veto `played 3.5h ago (<4h rule)`. ✔
- Song Y2 (never played itself) whose **artist** had a different song play 0.5h ago → weight 0.0, veto `artist played 0.5h ago (<1h rule)`. ✔
- Boundary: played exactly 4.0h ago → **not** vetoed (strict `<`), weight 1.30. Consistent with the documented rule ("< 4").

### 4. All-zero edge
- Category where every candidate is weight 0 (all played today at that hour): `pick_song_for_clock` returned **None** — no `random.choices` ValueError, because zero-weight candidates are filtered *before* the draw (`if w > 0`) and an empty eligible list short-circuits to None. Empty pool also returns None. Sane fallback confirmed.

### 5. Idempotency
- Second `compute_plan_for_date` same day: same plan_id (418), decisions wiped and rewritten (12 → 12), exactly 1 plan row for the date, no duplicate accumulation. Clean reset. ✔
- BUT: recompute also resets `status` back to `'pending'` and NULLs `approved_at` — see Bug 2.

### 6. Determinism / repeat pressure (200 picks, one hour, 13 non-zero candidates)
- Max share 14.5% (`ZZP_bound4`, expected 10.3%) — well under the 30% dominance threshold; distribution tracks the weight proportions (0.05-weight song picked 1/200 = 0.5% vs 0.4% expected).
- Zero-weight songs picked: **NEVER** (0/200 across 4 vetoed candidates). ✔

### 7. Existing tests (run against live DB by project design)
- `py -m pytest tests/test_rotation_ai_engine.py -q` → **28 passed** (1.48s)
- `py -m pytest tests/test_rotation_db.py -q` → **40 passed** (0.80s)

## 🐛 Bugs found

1. **HIGH — The USP is completely inert on this station's real configuration.** The only clock on the auto-schedule grid (id 3701, day 5 hours 18–24) has all Song slots with `category_id=NULL` (`selection_mode='random_from_category'`, no filter_json, no specific pins). The engine skips such slots (`rotation_ai_engine.py:551-553` `if cat_id is None … continue`) *and* the live consult gate in `core/scheduler/engine.py:749` requires `category_id is not None` — so neither plan computation nor on-air picks ever involve the rotation AI. Evidence: every plan ever computed on the live DB (ids 372/373/418) has 0 decisions; my compute on the copy for the populated weekday also yielded 0. Either the Clock Editor is failing to persist `category_id` for `random_from_category` slots, or the engine should resolve category from the same fallback chain the scheduler uses. Songs currently rotate via the scheduler's plain random+separation fallback only.

2. **HIGH — Hourly tick destroys plan approval, closing the AI gate ~1h after it opens.** `tick()` unconditionally calls `compute_plan_for_date()`, which calls `reset_ai_rotation_plan()` → `status='pending'`, `approved_at=NULL` (`core/database.py:1601-1619`). Dynamically demonstrated: approve → recompute → status is `'pending'` again. Meanwhile the 5 PM auto-apply (`ui/main_window.py:1286-1318`) is one-shot per day via the `last_rotation_auto_apply_date` sentinel — after the 18:00 tick resets the plan to pending, auto-apply will not re-fire (sentinel already stamped). Net: the scheduler's gate (`status in ('approved','auto_applied')`, engine.py:756-757) is satisfied for at most one hour per day; every other hour, AI picks are silently skipped. Even during that hour, the decisions the operator approved get wiped and re-randomized by the next tick.

3. **MEDIUM — Rest decisions duplicated per song-slot, inflating operator-facing stats.** A clock with N same-category Song slots writes the same rest row N times per hour (only `slot_idx` differs). Observed: 2-slot clock over 2 hours → songs 4057/4058 each rested twice per hour (8 rest rows, `rested_count=8`, for 4 unique song-hour rests). The Rotation Health / Daily Plan Review screens and the plan envelope counters (`total_changes`, `rested_count`) double-count accordingly. Real clocks commonly have 4–10 song slots, so the inflation factor is large.

4. **LOW — Negative "hours ago" in veto reasons on afternoon recompute.** Plan simulation pins `sim_now` to noon of plan_date (`rotation_ai_engine.py:518-519`). Any song played *after* noon yields negative `hours_since`, which passes the `< 4` veto check and produces operator-visible reasons like `played -3.0h ago (<4h rule)` (dynamically reproduced). Any afternoon play therefore rests the song for **all** remaining hours of the plan, and the reason string shown in Daily Plan Review is nonsense.

## ⚠ Anomalies worth operator review

- **Grid nearly empty**: `auto_schedule` covers only Saturday 18:00–24:00. All other 162 week-hours have no clock, so plan computation is a no-op for them regardless of Bug 1.
- **Artist-veto rests can list songs that never played**: a song can be "rested" purely because a *different* song by the same artist played <1h before noon. This is by design (1h artist rule) but the rest list in Daily Plan Review will show never-played songs, which may confuse the operator.
- **4h boundary is exclusive**: a song played exactly 4.0h ago is fully eligible (weight up to 1.56). Fine per spec ("< 4"), just noting the boundary.
- **Calendar-day slot bucketing**: a 23:59 play counts as "yesterday" one minute later (slot weight 0.05, not 0.0). The <4h overall veto masks it in practice, but if the ladder is ever consulted without the veto (e.g. explain UI), the bucket label may look odd.
- **Approve-then-recompute UX**: even ignoring Bug 2's gate effect, manual "refresh" from the Hub silently discards an approved plan's decisions and re-randomizes picks with no confirmation.
