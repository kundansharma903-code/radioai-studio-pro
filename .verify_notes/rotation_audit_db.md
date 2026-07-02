# Rotation AI — Data Layer Audit
Audited 2026-07-02 (read-only). Live DB: `C:\Users\hp\AppData\Local\RadioAI Studio Pro\Database\radioai.db` (probed via `mode=ro` URI; zero writes).

## Schema & query map

### Tables (schema.sql + mirrored in `Database._ensure_ai_rotation_tables`, core/database.py:1269)
| Table | Key constraints | Written by | Read by |
|---|---|---|---|
| `ai_rotation_plans` (schema.sql:650) | `plan_date UNIQUE` — 1 plan/day guaranteed | `get_or_create_ai_rotation_plan` (database.py:1581), `reset_ai_rotation_plan` (:1601), `mark_*` approve/discard/auto-apply (:1690/:1703/:1724), `update_ai_rotation_plan_stats` (:1661) | scheduler consult gate (core/scheduler/engine.py:755-757), hub (ui/scheduling_automation_hub.py:495), rotation_health, daily plan review, main_window 5-PM tick (ui/main_window.py:1307) |
| `ai_rotation_decisions` (schema.sql:673) | FK plan_id → plans **ON DELETE CASCADE**; clock_id → clocks CASCADE; song_id/source_cat/target_cat → NO ACTION. **No UNIQUE on (plan_id, clock_id, hour, slot_idx, song_id, action)** | `add_rotation_decision` (:1621) via `RotationAIEngine._decide_for_slot` (rotation_ai_engine.py:580); wiped by reset/discard/delete_clock (:3059) | `get_rotation_decisions_for_date` (:1738), `_for_clock` (:1763), `get_rotation_summary_for_date` (:1894) → Daily Plan Review + Rotation Health |
| `sister_groups` / `sister_group_members` (schema.sql:625-638) | PK (group_id, category_id) + **UNIQUE(category_id)** → one group per category enforced at DB level; members CASCADE on group AND category delete | `create_sister_group` (:1343), `add/remove_category…` (:1428/:1471), `delete_sister_group` (:1419) | `get_sister_pool_for_category` (:1558) → engine candidate pool; `get_sister_groups` (:1490) → AI Magic hub |
| `broadcast_log` (schema.sql:363) | `played_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))` | **single writer**: `Database.log_play` (:261) — called from core/audio_engine.py:352 and ui/studio.py (4866/5573/5724/5993) | all recency queries below |

### Indexes (verified present in live DB)
- `idx_broadcast_song(song_id, played_at)`, `idx_broadcast_when(played_at)`, `idx_broadcast_type(entry_type)` (schema.sql:530-533)
- `idx_rotation_decisions_{date, clock_date, song, plan}` (schema.sql:690-697)
- `idx_sister_members_{group, category}` + autoindexes from PK/UNIQUE

### Recency-query coverage
| Query | Index used | Verdict |
|---|---|---|
| `get_song_last_played_at` (:1830) `song_id=? AND entry_type='song'` | idx_broadcast_song prefix | OK |
| `get_last_played_map` (:1844) GROUP BY song_id | idx_broadcast_song | OK |
| `get_artist_last_played_at` (:1857) join on `s.artist=?` | no index on songs.artist; 395-row scan then idx_broadcast_song per song | acceptable now; watch at scale |
| `get_song_last_played_in_hour` (:1879) `song_id=?` + strftime filter | idx_broadcast_song prefix, then per-song filter | OK |
| `get_next_song` 7-day/3-day subqueries (:205/:213) `played_at > datetime(...)` | idx_broadcast_when range | OK |
| `_recent_artists/_recent_song_ids` (scheduler/engine.py:1216/:1231) `played_at >= ?` | idx_broadcast_when | OK |
| `get_broadcast_log_for_hour` (:345) `date(played_at)=?` | **function on column → no index → full scan** | ~ms at 2.7k rows; noticeable at 70k+/yr (Final Log screen only, not on-air path) |
| `get_category_songs_ranked` (:1988) subquery scans whole broadcast_log | idx_broadcast_song for grouping | OK, screen-only |
| decisions by date / clock+date / plan | dedicated indexes | OK |

## Date/time consistency verdict

**Writer**: `log_play` stamps `played_at` with `datetime('now','localtime')` → format `YYYY-MM-DD HH:MM:SS`, **local (IST) clock**. Live probe confirms: all 2,764 rows length-19, zero `T`-separator rows.

| Comparison site | Clock | Consistent with localtime storage? |
|---|---|---|
| `get_next_song` 7-day veto (database.py:205) `datetime('now','localtime','-7 days')` | local | ✅ |
| `get_next_song` 3-day slot veto (:213) | local | ✅ |
| `get_song_last_played_in_hour` (:1879) `DATE(played_at)` / `strftime('%H')` vs Python `now.date()` (rotation_ai_engine.py:305) | local vs local | ✅ |
| 4-hr song / 1-hr artist vetoes — Python `datetime.now()` vs stored string via `fromisoformat` (rotation_ai_engine.py:293/:325/:337) | local vs local | ✅ (fromisoformat parses space separator on Py ≥3.11) |
| scheduler `_recent_*` (scheduler/engine.py:1210/:1226) Python `_dt.now()` cutoff string | local | ✅ |
| `get_hourly_ad_usage` (database.py:3491-3492) | local | ✅ |
| `get_song_recent_plays_count` (database.py:1975) `datetime('now', '-N days')` | **UTC** | ❌ mixed — see Bug 4 |
| campaign end-date filter (database.py:3478) `c.end_date >= date('now')` | **UTC** | ❌ adjacent (spots, not rotation) — see Bug 5 |
| `ai_rotation_plans.created_at` DEFAULT CURRENT_TIMESTAMP (schema.sql:660) | **UTC** | ⚠ display-only skew; `approved_at`/`discarded_at` are Python-local ISO (:1694/:1708) → same row mixes clocks |
| `plan_date`, `decision_date`, `purge` cutoff (`date.today()`, :1792), scheduler consult `_date.today()` (scheduler/engine.py:754), 5-PM net (`main_window.py:1299`) | local everywhere | ✅ |

**Verdict: the on-air veto chain (played-today slot veto, <4 hr song, <1 hr artist, 7-day/3-day separation) is uniformly LOCAL — no midnight skew.** The two UTC stragglers are a UI stat (over-counts by up to 5.5 h of plays) and the campaign end-date check (spot domain). Plan `created_at` is UTC and shows 5.5 h early if ever displayed raw (live row confirms: created_at `04:44:23` for a tick at `10:14` IST).

## Live-DB probe results (read-only)

- `ai_rotation_plans`: 3 rows — `2026-07-02 pending`, `2026-05-16 pending`, `2026-05-15 pending`; **all zero counters**.
- `ai_rotation_decisions`: **0 rows** for every plan. 0 orphans, 0 duplicates, 0 decision_date≠plan_date mismatches.
- Cause of zero decisions: `auto_schedule` has cells **only for day_of_week=5 (Saturday)** — 6 cells. Today (Thu) the engine walks zero cells (rotation_ai_engine.py:526-530). The feature has effectively never produced a decision on-air.
- Plans from 2026-05-15/16 are >14 days old and still present → confirms retention purge never runs (Bug 3).
- `broadcast_log`: 2,764 rows, `2026-04-11 16:38:03` → `2026-07-02 10:22:14`, uniform `YYYY-MM-DD HH:MM:SS`. entry_type mix: song 1841 (1629 with song_id — 212 NULLed by song deletion), sweeper 480, spot 238, jingle 155, stitcher 38, sotg 12. **No non-song row carries song_id** → entry_type-filter inconsistencies are currently latent.
- `sister_groups`: **empty** (feature unused so far). 0 orphan members.
- Settings: `rotation_ai_engine_enabled=1`, `rotation_ai_last_tick_at=2026-07-02T10:14:23`, `rotation_ai_last_plan_date=2026-07-02`, `rotation_ai_last_error=''`, `last_rotation_auto_apply_date=2026-05-16`.
- App connections run `PRAGMA foreign_keys=ON` (core/database.py:41) → declared CASCADEs and NO-ACTION FK enforcement are live at runtime.

## 🐛 Bugs found

1. **HIGH — hourly tick silently destroys operator approval; AI picks stop within ≤1 h of approval.**
   `RotationAIEngine.tick()` (rotation_ai_engine.py:475-481) unconditionally calls `compute_plan_for_date` → `reset_ai_rotation_plan` (database.py:1601-1619), which wipes decisions and resets `status='pending'`, `approved_at=NULL` — even when status is `approved` or `auto_applied`. The scheduler only consults the AI when status ∈ (approved, auto_applied) (scheduler/engine.py:756-757). So: operator approves (main_window.py:1245, told "plan is now live") → next hourly tick flips it back to pending → AI picks stop. Worse after 5 PM: the auto-apply net (main_window.py:1287-1321) is sentinel-guarded to fire **once per day**, so after the first post-17:00 tick resets status, the plan stays `pending` for the rest of the day. Net effect: the USP feature is live for at most ~1 hour per day. On-air impact: silent fallback to random+separation — no error, no operator signal. Fix direction: `tick()` should skip recompute (or preserve status) when today's plan is approved/auto_applied.

2. **MEDIUM (latent) — `delete_song` will start failing once decisions exist.**
   `ai_rotation_decisions.song_id REFERENCES songs(id)` with NO ACTION (schema.sql:682) + `PRAGMA foreign_keys=ON` ⇒ `delete_song` (database.py:117-157) raises IntegrityError and rolls back if the song appears in any decision row — it NULLs broadcast_log/ai_daily_log/ai_decisions but never touches `ai_rotation_decisions`. Combined with Bug 3 (decisions never purged), any song ever named in a decision becomes permanently undeletable. Same hole in `delete_category` (database.py:4281-4293) vs `source_category_id`/`target_category_id`. Currently masked only because the live decisions table is empty. (`delete_clock`, database.py:3059-3064, handles its FK correctly — commit d65ba98 verified.)

3. **MEDIUM — `purge_old_rotation_decisions` (database.py:1786) is dead code; retention never runs.**
   Docstring claims "run by the engine's nightly maintenance tick"; grep shows zero callers outside tests. Live DB confirms: plans from 2026-05-15/16 (>14 days) still present. Growth is small (1 plan/day + decisions/day), but the promised 14-day retention contract is unimplemented, and it amplifies Bug 2.

4. **LOW — `get_song_recent_plays_count` (database.py:1975) compares UTC `datetime('now','-N days')` against localtime `played_at`.**
   In IST the cutoff lands 5 h 30 m too early → "last 7d plays" tooltip in Rotation Health (ui/rotation_health.py:416) over-counts plays that happened 7d–7d5.5h ago. Display-only; not in the veto path. (Also builds the interval by f-string — int-cast so not injectable, but parameterize for hygiene.)

5. **LOW (adjacent, outside rotation) — campaign end-date filter uses UTC `date('now')` (database.py:3478).**
   Between 00:00 and 05:30 IST, `date('now')` is still yesterday → a campaign whose end_date was yesterday keeps airing spots up to 5.5 h past expiry. Rotation-adjacent because it shares the same mixed-clock root cause.

6. **LOW — plan timestamps mix clocks within one row.**
   `created_at` = CURRENT_TIMESTAMP (UTC, schema.sql:660/database.py:1306); `approved_at`/`discarded_at` = Python local ISO (database.py:1694/1708/1729). Nothing compares them today, but any future "approved N minutes after creation" math or raw display is off by 5.5 h. Same UTC default on `sister_groups.created_at` / `ai_rotation_decisions.created_at` — the latter is used as an ORDER BY key (:1759, :1782), where second-granularity UTC is fine for ordering rows created in sequence.

## ⚠ Design risks

- **No UNIQUE on decisions** for (plan_id, clock_id, hour, slot_idx, song_id, action). Integrity relies on reset-before-write inside a single tick. Concurrent writers (hourly QThread tick + Hub Refresh button main_window.py:1144 + Rotation Health refresh ui/rotation_health.py:1231 can overlap) can interleave reset/insert and produce duplicates or torn plans. `add_rotation_decision` commits per-row (:1658) — a mid-compute crash leaves a half-written plan marked 'pending' with stale stats. Live probe shows 0 dupes today (trivially — 0 rows).
- **Approved plan ≠ what airs.** The scheduler's consult path calls `pick_song_for_clock` (rotation_ai_engine.py:431) which recomputes weights live and does a fresh weighted-random pick; the persisted decisions (rest/promote/pick rows) are an audit trail, not a dispatch contract. Operator "approves" a preview that dispatch does not replay. Decisions' `action='pick'` rows are also invisible in Rotation Health buckets (`get_rotation_summary_for_date` only buckets rest/promote, database.py:1946-1952).
- **Plan simulated at noon** (`sim_now` = 12:00, rotation_ai_engine.py:518-519): the preview's 4-hr/1-hr vetoes are evaluated against noon, live dispatch against actual time — another preview/dispatch divergence source.
- **entry_type filter fragility**: `get_song_play_stats` (database.py:103), `get_next_song` 7-day/3-day subqueries (:202-216) and `get_category_songs_ranked` (:2007-2015) do not filter `entry_type='song'`; they are correct today only because every writer nulls song_id on non-song rows (core/audio_engine.py:351, ui/studio.py:4852). Any future writer that attaches song_id to a stitcher/sweeper row silently corrupts the 7-day veto and play counts.
- **Sister-group invariants split-brain**: one-group-per-category is DB-enforced (UNIQUE), but 2≤members≤5 is app-enforced only. `delete_category` cascades a member out (FK CASCADE) with no auto-delete of a now-1-member group — pool degenerates to a single category silently. Read-side filter (:1512) only hides 0-member groups.
- **System clock moved backward**: plan_date keys are plain local dates; `get_or_create` returns the existing (already reset/consumed) plan for the repeated day, and `purge` (`plan_date < today-14`) simply skips "future" plans — no corruption, but `last_rotation_auto_apply_date` sentinel from the "future" day blocks the 5-PM net only if the dates match exactly; a backward jump to an earlier date makes the sentinel mismatch and the net re-fires — acceptable. `rotation_ai_last_plan_date` is write-only in production (read by tests only) — no runtime consumer to break.
- **Legacy table dead-references**: `delete_song` NULLs `ai_decisions` (:141) — a legacy AI table distinct from `ai_rotation_decisions`; easy to conflate in future maintenance.

## Test coverage gaps

Existing: `tests/test_rotation_db.py` (sister CRUD, plan CRUD, decision validation, purge, hour-slot queries), `tests/test_rotation_ai_engine.py` (weight curve, vetoes, plan compute, lifecycle), `tests/test_rotation_pickers.py` (scheduler pickers/separation). Solid unit coverage of the happy path. Missing:

1. **No test that an approved/auto_applied plan survives a subsequent `tick()`** — the exact Bug-1 scenario. `test_compute_plan_idempotent_reset` (test_rotation_ai_engine.py:559) actually enshrines the wipe.
2. No test that `delete_song`/`delete_category` succeed while `ai_rotation_decisions` rows reference them (Bug 2) — with `foreign_keys=ON`.
3. No caller-level test that the 14-day purge is actually scheduled/invoked (Bug 3) — only the helper itself is tested.
4. No timezone-skew test (e.g. freeze SQLite vs Python clocks apart) for `get_song_recent_plays_count` or any `datetime('now')` usage.
5. Tests seed `played_at` via Python `isoformat()` → `T`-separator, production writes space-separated — tests exercise a format production never produces; a lexical `played_at > ?` comparison bug across formats would not be caught (live data is uniform, so latent).
6. No concurrency test for tick vs Hub-Refresh double-compute (duplicate-decision risk).
7. No test that the scheduler consult gate behaves across the midnight boundary (plan for yesterday still approved at 00:01, today's not yet computed → AI silently off until first tick — worth an explicit expectation).
