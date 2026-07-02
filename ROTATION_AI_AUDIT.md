# Rotation AI (Time-Slot Freshness) — USP Feature Audit

> ## ⚡ FIX STATUS — 2026-07-02 (same-day supervised fix session)
> All CRITICAL + MEDIUM bugs below were FIXED on the working tree (uncommitted):
> - **BUG-1 FIXED** — `compute_plan_for_date` now preserves approved/auto_applied/
>   discarded plans (status guard before reset; pending/absent still recompute).
> - **BUG-2 FIXED** — new `db.get_active_rotation_decisions()`; `_pick_song` chain:
>   plan-picks honored first → engine consult → ladder minus rest → never-stall
>   unfiltered fallback. 60s-TTL cache (approval live within a minute).
> - **BUG-3 FIXED** — REST ids excluded from the normal ladder candidate sets.
> - **BUG-4 (code half) FIXED** — NULL-category slots use an all-songs pool
>   (no boost); scheduler consult bypass removed. **Data half still pending:**
>   auto_schedule grid has only Saturday cells; sister_groups empty — operator
>   must assign clocks/groups for the feature to act on other days.
> - **MED fixes** — Hub Refresh now queues tick onto the engine thread + respects
>   the enabled flag; artist veto casefold+strip; rest rows deduped per
>   (clock,hour,song); purge wired (daily, `rotation_ai_last_purge_date`);
>   `delete_song`/`delete_category` clean `ai_rotation_decisions` first.
> - **Tests** — 79 rotation tests green incl. new: approve-survives-tick,
>   discarded-preserved, NULL-category-decisions, rest-dedupe, casefold-veto,
>   gate, plan-pick-honored, rest-excluded, never-stall, delete-cleanup
>   (`test_rotation_consume.py` is new). The old `test_compute_plan_idempotent_reset`
>   (which enshrined BUG-1) was rewritten.
> - **Known litter:** 5 orphaned `phaseC-*` categories (ids 154-158) from an
>   earlier interrupted test run — cleanup needs operator confirmation.
>
> ## 🧪 END-TO-END SIMULATION — 2026-07-02 (post-fix proof)
> Full backend simulation on a temp COPY of the live DB (live DB verified
> untouched: quick_check ok, zero sim rows). Universe: 24 songs / 8 artists,
> 2 clocks (category + NULL-category), 6 days seeded history, 4 broadcast
> hours simulated. **13/13 checks passed:**
> - Plan compute: 28 decisions for the category clock (24 rest + 4 pick);
>   123 decisions for the NULL-category clock (all-songs pool) — BUG-4 dead.
> - Every REST traced to a genuinely-played song; zero duplicate rest rows.
> - Approve → recompute tick → plan id, APPROVED status, and all 151
>   decision row-ids byte-identical — BUG-1 dead.
> - Scheduler aired the day: plan pick honored as the hour's first song in
>   4/4 hours; RESTED songs aired 0 times (random baseline would have aired
>   2 rested songs); zero None picks (never-stall held).
> - Discard sticks across ticks; discarded plan has no on-air authority.
> - TTL probe: a long-running scheduler picks up a mid-hour approval after
>   cache expiry (≤60s). Separation probe: a just-aired plan pick is NOT
>   repeated — the 240-min window pushes the pick to the ladder (a same-day
>   compressed-time sim run also demonstrated this veto path live: 3/4
>   honored + graceful ladder fallback, zero rest violations).
> Sim artifact note: in the yesterday-anchored run each hour showed the same
> plan pick 4×, because backdated rows sit outside the real-now separation
> window — the separation probe above proves production behavior repeats
> nothing back-to-back.

> 4 independent audits (engine algorithm · scheduler consumption · data layer ·
> dynamic behavioral probes on a read-only DB snapshot), 2026-07-02.
> Detailed per-audit reports: `.verify_notes/rotation_audit_*.md`.
> Live DB was never written to; probes ran on temp copies (mode=ro verified).

## Feature kaise kaam karta hai (verified walkthrough)

1. **RotationAIEngine** (`core/rotation_ai_engine.py`) — QThread + 1-hour tick.
   Har tick par aaj ka **daily plan** compute karta hai: har active clock ke
   har hour ke liye, candidate songs ko **Time-Slot Freshness weight** deta hai:
   - `slot_age_days` = us hour-H mein song last kab baja (weekday-agnostic)
   - Ladder: today→0.00 (veto) · yest→0.05 · 2d→0.30 · 3d→0.60 · 4d→0.90 ·
     5-6d→1.00 · 7+→1.00 · never→1.30; primary category ×1.2 boost
   - Vetoes: <4hr same-song, <1hr same-artist
   - Decisions (`rest`/`promote`) → `ai_rotation_decisions`; envelope →
     `ai_rotation_plans` (status: pending → approved / discarded / auto_applied)
2. **Operator approval** — Daily Plan Review screen; 5-PM one-shot timer
   auto-applies agar undecided.
3. **SchedulerEngine `_pick_song`** (Phase E5) — plan status approved/auto_applied
   hone par AI se pick consult karta hai, warna apna normal random ladder.

## ✅ Jo bilkul sahi hai (dynamically proven)

- **Core math EXACT spec-compliant**: saari 8 ladder values, ×1.2 boost (1.56
  measured), dono vetoes fire hote hain, midnight bucketing sahi.
- All-zero-weight pool → safe None (no crash); 200-pick histogram healthy
  (max share 14.5%, zero-weight songs picked 0/200 — repeat protection works).
- Recompute row-idempotent; no duplicate/orphan rows in live DB; broadcast_log
  timestamps uniform localtime; dono test suites (28+40) pass.

## 🔴 CRITICAL bugs (4 audits ne independently confirm kiya)

### BUG-1 — Hourly tick approved plan ko wapas `pending` kar deta hai
`rotation_ai_engine.py:514` tick → `database.py:1601 reset_ai_rotation_plan`
**unconditionally** aaj ke plan ko pending par reset karta hai + decisions wipe.
Operator approve kare → agla tick (≤1 ghanta) approval uda deta hai → scheduler
ka status-gate (`scheduler/engine.py:756`) consult band kar deta hai. 5-PM
auto-apply **one-shot sentinel** hai, dobara nahi chalta.
**Net effect: USP feature din mein max ~1 ghanta live rehta hai.**
(Dynamic probe ne demonstrate kiya: approve → recompute → status wapas pending.)
Note: `test_compute_plan_idempotent_reset` yeh galat behavior enshrine karta hai.

### BUG-2 — Scheduler approved DECISIONS ko kabhi padhta hi nahi
`pick_song_for_clock` `ai_rotation_decisions` read nahi karta — live pick har
baar fresh weighted-random re-roll hai. Jo plan operator ne Daily Plan Review
mein approve kiya, woh sirf **preview** hai — hawa mein wahi nahi bajta.
Kaunsa pick aired hua, wapas kuch log nahi hota (Rotation Health audit blind).

### BUG-3 — REST decisions fallback ladder ko constrain nahi karte
Jab consult skip hota hai (jo BUG-1 ke kaaran din ka zyada-tar time hai),
normal `random.choice` ladder rested songs ko bhi utha leta hai. Rest = cosmetic.

### BUG-4 — Production data mein feature INERT hai
On-air clock ke Song slots mein `category_id=NULL` hai → engine skip karta hai
aur consult bypass (`scheduler/engine.py:749`) → **aaj tak ke har plan mein
0 decisions bane hain.** Auto-schedule grid mein sirf Saturday cells assigned;
sister_groups bhi khaali. (Aadha data-config issue, aadha robustness bug —
NULL-category slot ko bhi handle karna chahiye.)

## 🟠 MEDIUM

5. **Hub "Refresh" UI-thread par tick chala deta hai** — worker tick se race +
   enabled-toggle ignore karta hai (`scheduling_automation_hub.py`).
6. **Artist veto exact-match hai** — case/whitespace sensitive; "Arijit Singh"
   vs "arijit singh " alag artists gine jaate hain → veto miss.
7. **`purge_old_rotation_decisions` dead code** — koi caller nahi; plans/decisions
   unbounded grow karenge. Saath mein: decisions rows ban jaane ke baad
   `delete_song`/`delete_category` FK error se fail honge (FK NO ACTION +
   foreign_keys=ON, koi cleanup nahi).
8. **Rest rows per-song-slot duplicate hote hain** — rested_count inflated
   (probe: 8 reported vs 4 unique).

## 🟡 LOW

9. Boot par double-tick; dead cache fields; `start()` docstring galat.
10. 2 UTC-vs-localtime stragglers: `get_song_recent_plays_count` +
    campaign `date('now')` end-date check (core veto chain localtime-consistent
    hai, yeh do bahar reh gaye).
11. Noon-anchored `sim_now` → operator ko "played -3.0h ago" jaise negative
    reason strings dikhte hain afternoon plays ke liye.

## Test coverage gaps

- Approve-survives-tick ka koi test nahi (isi liye BUG-1 kabhi nahi pakda gaya)
- 5-PM auto-apply ka zero test; consult path ka zero test
  (`test_rotation_pickers.py` rotation engine install hi nahi karta)
- Engine tests LIVE `%LOCALAPPDATA%` DB par chalte hain aur teardown mein aaj ka
  plan delete karte hain — on-air machine par mat chalao.

## Recommended fix order (operator decision pending)

| # | Fix | Effort | Impact |
|---|---|---|---|
| 1 | Tick approved/auto_applied plan ko preserve kare (reset sirf pending/new-day) | S | USP poore din live |
| 2 | Scheduler consult decisions ko read kare + REST fallback ladder ko bhi filter kare + aired pick decisions mein mark ho | M | Approve = jo bajta hai |
| 3 | NULL-category slot handling + operator ko config warning (grid/sisters khaali) | S | Feature actually active |
| 4 | Artist normalization (casefold+strip), rest-row dedupe, purge wiring + delete_* cleanup | S | Correctness + hygiene |
| 5 | Refresh → worker-thread tick + enabled-gate; UTC stragglers; reason strings | S | Polish |
| 6 | Naye tests: approve-survives-tick, 5-PM auto-apply, consult path | M | Regression guard |
