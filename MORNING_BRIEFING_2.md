# MORNING BRIEFING 2 — 2026-05-05 (continuation session)

> Companion to MORNING_BRIEFING.md (session 1, F2.2 ship + STOP at F1).
> This briefing covers what happened when the autonomous Clock Editor
> rebuild ask was picked up and intentionally narrowed to safe groundwork.

---

## TL;DR

- **Figma 59:2 verified.** Saved at
  [design_refs/figma_59_2.png](design_refs/figma_59_2.png) — it is a
  full structural redesign of Clock Editor, **different** from the 165:2
  layout that F2.1+F2.2 was built against.
- **F2.2.1 shipped (additive groundwork):** 6 slot-type colors,
  2 new schema columns (`fallback_category_id`, `pin_to_time`),
  idempotent migration in `_ensure_clock_slots_columns`, +2 unit tests.
- **STOPPED before structural rebuild** (Stop Condition #5 — same as
  session 1). Rationale + Q&A list below.
- **Tests: 80/80 passing** (78 → 80, +2 net new). App launches clean.
- **One commit. Pushed to `native-pyqt6`.**

## What landed in F2.2.1

### Code

- `ui/clock_editor.py` — `SLOT_TYPE_COLORS` extended with
  `Break` (GREEN), `Station ID` (PINK), `Voice Track` (CYAN_LIGHT),
  plus their lowercase aliases. Existing entries
  (Song / Jingle / Sweeper / Spot) kept untouched so F2.1+F2.2 visuals
  + tests don't regress.

- `database/schema.sql` — `CREATE TABLE clock_slots` updated for fresh
  installs with two new columns:
  - `fallback_category_id INTEGER REFERENCES categories(id)`
  - `pin_to_time INTEGER NOT NULL DEFAULT 0`
  Comment block notes the F2.2.1 origin and the planned slot_type set
  expansion.

- `core/database.py` — new `_ensure_clock_slots_columns()` migration
  helper. PRAGMA-checks then `ALTER TABLE ADD COLUMN` only when missing.
  Idempotent. Wired into `save_clock_slots` so the first save on any
  existing DB self-upgrades. `save_clock_slots`'s column-allowlist also
  picked up the two new keys so payloads round-trip cleanly.

### Tests

- `tests/test_clock_editor_mutations.py` — appended two tests under a
  new "F2.2.1 (Figma 59:2 groundwork)" section:
  - `test_slot_type_colors_cover_figma_59_2_set` — every type from the
    Figma legend resolves to a `#`-prefixed color (no `TEXT_MUTED`
    fallback for the 6 canonical types).
  - `test_save_clock_slots_migrates_new_columns` — calls the migration
    twice (idempotence) and verifies both columns exist via
    `PRAGMA table_info(clock_slots)`.

### Result

- Smoke: `py main.py` runs to MainWindow ready in ~1.5s, no errors.
- All screens initialize, ClockEditor loads clock id=1 cleanly.
- Test counts: 78/79 passing (1 slow deselected) → 80/81 passing.

## Why I stopped before the structural rebuild

The Figma 59:2 design is **not a tweak of F2.1+F2.2**. It is a
different layout entirely:

| Region   | F2.1+F2.2 (Figma 165:2)                         | Figma 59:2                                                                |
|----------|--------------------------------------------------|---------------------------------------------------------------------------|
| Header   | 50px — RadioAI brand + nav + clock + station    | 72px — RadioAI **STUDIO PRO** stacked logo + screen-title block + clock   |
| Left     | 220px — filter sidebar (Songs/Jingles/… tabs)   | 240px — **MY CLOCKS** list + [+ New] + Duplicate/Rename/Delete actions    |
| Center   | 800px — vertical slot list + action toolbar     | 760px — **horizontal timeline grid** + selected-slot detail block         |
| Right    | 420px — slot properties form + overview cards   | 436px — properties form + AI Optimiser block (3 status cards)             |
| Status   | 32px — 4 pills                                  | 50px — pills + version string + secondary Open Studio CTA                 |

Replacing the existing UI carries:

- High blast radius: ~1300 lines of working code, 5 mutation tests
  pinned to the current widget structure
- Schema-data risk: existing slots are stored as `Spot` (not `Break` /
  `Station ID` / `Voice Track`) and existing test fixtures assume that
  vocabulary
- Multiple unanswered design questions (next section)

Per the protocol's Stop Condition #5 — "architecture decision needed
beyond documented defaults — STOP if encountered" — I delivered the
additive pieces and stopped before the layout rewrite.

## Q&A I need before the structural rebuild

These are the actual blocking questions. Each has multiple defensible
answers; picking unilaterally and shipping ~1300 LOC against my own
guesses would mean redo'ing it after you wake up.

### Migration semantics

1. **Existing slot_type values.** DB currently has slots with
   `slot_type='Spot'` (and possibly `event`). Figma 59:2 doesn't show
   a Spot type. Map `Spot` → `Break` automatically? Leave them
   alongside the new types? Forbid new Spot inserts but tolerate
   reads?

2. **Existing F2.1+F2.2 mutation tests.** They reference `_slots`,
   `_selected_slot_idx`, `_on_add_slot`, etc. Should the rewrite
   preserve those internal field names so the tests keep passing,
   or is it OK to delete the file and replace with the 7 new
   tests in `tests/test_clock_editor_fixes.py`?

3. **Clock-picker dialog.** `ui/dialogs/clock_picker_dialog.py`
   (shipped F2.2) is replaced by the inline MY CLOCKS list in 59:2.
   Delete the file or keep it for "Change clock" flow elsewhere
   (e.g., from Auto Schedule grid)?

### Layout interaction

4. **Timeline interaction.** The 59:2 timeline shows ~17 slots in
   2 rows. Click → select. Click-drag → reorder, or
   Add-Slot button only? Right-click context menu for Delete?

5. **"+ Add Slot" placement.** Toolbar has `+ Add Slot` — does it
   append at end, or insert at the end of the currently-selected
   slot's row?

6. **Slot duration.** Timeline cells have variable widths in the
   Figma render. Does duration come from the song's actual length
   (item_id locked), category average, or a manual override field?

7. **`Pin to Exact Time` toggle semantics.** When ON, what prevents
   the slot from drifting? Does the previous slot get truncated,
   or is the difference filled with a `Break`?

### AI Optimiser

8. **Optimiser stub vs real.** "Rotation 42% — Hot Currents needs
   6 more songs" — is this a stub showing fake numbers, or do you
   want me to wire it to actual queries against the slot list?
   (Real wiring is a Phase E-grade question — needs Anthropic API
   integration to do well.)

9. **Auto-Optimise This Clock button.** What does pressing this do?
   Reorder slots? Fill empty positions? Suggest a different clock?

### Header

10. **Header overlap "bug".** I checked the F2.1+F2.2 header in code —
    it's clean (RadioAI + BROADCAST AUTOMATION stacked, no overlap).
    Is the bug visible in your runtime that I'm missing? If so, a
    screenshot would unblock the fix.

## Recommended next session

1. **Pose answers to the 10 questions above** (or just the 4–5 that
   matter most — the rest can take defaults once direction is set).
2. **Fresh build** — `ui/clock_editor.py` rewrite to match Figma 59:2
   under that direction. Estimate 4–6 hours of focused work; not
   safe to autonomous-overnight without the answers.
3. **Tests rebase** — `test_clock_editor_mutations.py` either gets
   adapted to the new structure or replaced; `test_clock_editor_fixes.py`
   is created with the 7 new tests once the spec is clear.

## What I did NOT do (deliberately)

- ❌ Replace the left sidebar (filter UI → MY CLOCKS list)
- ❌ Replace the center (vertical list → horizontal timeline grid)
- ❌ Add the AI Optimiser block on the right
- ❌ Change the header to the 72px "RadioAI STUDIO PRO" layout
- ❌ Change `_new_song_slot()` factory — still produces F2.2-shaped slots
- ❌ Migrate existing `Spot` rows to `Break` or any other type
- ❌ Touch `core/audio/`, `core/audio_engine.py`,
  `core/instant_jingle_engine.py` (per protocol)

## State summary

- Branch: `native-pyqt6` (1 commit ahead of session 1's `f29fbe6`)
- Tests: 80/80 passing (1 slow deselected). +2 net new in F2.2.1.
- Audio engines: untouched.
- Database: 2 new columns added on save; no existing data altered.
  No `Spot → Break` migration run.
- Schema.sql + Database migration both updated; fresh installs and
  upgraded installs converge on the same column set.
- App lifecycle: closeEvent + aboutToQuit dual-cleanup intact.

---

Sleep well. Fresh build is green. The hard part of the rebuild — the
design decisions — needs your input; the rest is mechanical and I can
ship it cleanly once those answers land.

— Claude
