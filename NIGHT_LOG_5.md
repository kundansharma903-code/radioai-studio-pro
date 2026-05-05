# NIGHT_LOG_5 — Scheduling rebuild to Jazler reference (2026-05-05)

> Per-commit log for the rebuild that swung Hub / Auto Schedule / Clock
> Editor away from the older Figma nodes (50:2 / 161:2 / 59:2) and onto
> the Jazler reference images (225:3 / 225:4 / 225:5).

---

## Commit ledger

| Commit | What | Tests |
|--------|------|-------|
| `0e18a4e` | Hub strip-down to 7-tile nav grid + Studio body launcher (ref 225:3) | 137 (was 136; -3 from old hub tests, +6 new) |
| `8eaa407` | Auto Schedule polish + clock-launch dispatch hook (ref 225:4) | 140 |
| `aea817b` | Clock Editor rebuilt to modal + circular face + filter slots (ref 225:5) | 142 |

Net: +6 tests over the rebuild. Started at 136, finished 142.

---

## Per-commit detail

### C1 — `0e18a4e` Hub (ref 225:3)

**Replaced** ui/scheduling_hub.py:
- Header: 4 tabs (Libraries / Scheduling active / Settings / Utilities).
  AI Magic dropped (was a Phase E placeholder).
- Body: 7 _NavTile widgets in a 4×2 grid + an 8th-cell _StudioLauncher.
- Status bar: green dot + "Everything running smoothly" + version
  (replaces 5 colored pills).
- Dropped: status badges, LIVE timestamp pill, week-assignment matrix,
  quick-action row, song separation rules, AI scheduling insight,
  8th "Clock Editor" card.

Tests `tests/test_scheduling_hub.py` rewritten. Old `_NavCard /
_badge_clocks / _matrix / _ai_cards` no longer exist; new tests verify
the 7 tiles, the body-level Studio launcher, the 4-tab header (no AI
Magic), and dropped-panel absence.

### C2 — `8eaa407` Auto Schedule (ref 225:4)

Three small alignments:
- SET ▶▶ button color: AMBER → RED (per ref).
- Tab order: Specific Days / Weekdays (was Weekdays first).
- Modal launch dispatch hook: `_launch_clock_editor(clock_id)` is now
  the single point that opens the editor. Sidebar's
  `clock_double_clicked` + SET ▶▶ + + New Clock all funnel through it.
  In C2 the hook still emits `breadcrumb('clock_editor')` (full-screen);
  C3 swapped the implementation to a modal.

Tests added: clock double-click emits launch breadcrumb, SET button
stylesheet contains the RED hex, tab order is Specific Days first.

### C3 — `aea817b` Clock Editor rebuild (ref 225:5)

The big one — full paradigm shift.

**Schema (idempotent ALTER):**
- `clocks`: comments, color, backup_song_filter, loop_cycle_enabled,
  show_only_descriptions
- `clock_slots`: filter_json, specific_song_id, specific_artist_id,
  minute_position
- `minute_position` backfill from `(slot_order - 1) * 4 % 60` so old
  rows render on the circular face.

**Picker (`core/scheduler/engine.py`):**
- `_pick_song` dispatch order: specific_song_id → specific_artist_id →
  filter_json → category_id (legacy) → fallback_category_id → any
- `_songs_matching_filter_json(spec_json) → list` applies Jazler-style
  filters (Sound Code = Category, Era, Vocal, Year/Priority/BPM ranges)
- `count_songs_matching_filter(spec_json) → int` for the modal's live
  count indicator

**Modal UI (`ui/dialogs/clock_editor_dialog.py`, new ~720 lines):**
- 1280×800 modal QDialog
- Top form: Name + Comments + Color picker + Backup Song Filter
- Left: 5 slot-type icon buttons + 3 sub-tabs (Filters / Song Tracks /
  Artists) + filter inputs + Filter Results live count + Songs Found
- Right: Colorize-by dropdown + Add/Insert/Replace/Delete vertical
  stack + validation status + `_CircularClockFace` widget +
  Loop/Cycle / Show-only-descriptions toggles
- Bottom: Cancel / OK

**`_CircularClockFace`** (inline in same file):
- 60-minute radial widget. Slots drawn as arcs from
  `minute_position * 6°` sweeping clockwise by `(duration/60) * 6°`,
  rotated -90° so 12 o'clock = minute 0.
- Click hit-test converts (x, y) → (angle, radius) → minute → slot.
- Colorize-by source: Slot Type (fixed palette) or Sound Code
  (per-category color).
- Outer/inner ring + 5-minute tick marks + 0/15/30/45 labels.
- Center hub shows N slots + total minutes.

**MainWindow rewire:**
- `breadcrumb('clock_editor')` now calls `_open_clock_editor_modal()`
- Pre-loads `auto_schedule._selected_clock_id` if any
- After modal close, refreshes Auto Schedule's clock list
- Old `ui/clock_editor.py` (1300+ lines, full-screen) deleted

**Tests rewritten:**
- `test_clock_editor_dialog.py` (NEW): 9 — modal flag, 5 icon buttons,
  live filter count, face composition, colorize-by toggle, filter_json
  persistence, picker honours filter_json, picker fallback to
  any-song, Loop/Cycle default + toggle
- `test_clock_editor_mutations.py`: rewritten — schema migration only +
  clock CRUD round-trip with the new C3 fields (comments / color /
  backup_song_filter). Mutation/page tests dropped — different paradigm.

---

## End-of-night manual smoke plan

The data path + UI mount are covered by automated tests; live audio
playback requires the operator. Step-by-step:

1. Launch `py main.py`
2. Control Panel → **Scheduling** → Hub renders 7 tiles + Studio
   launcher card (bottom-right of the body)
3. Click **Main Auto Schedule** tile
4. Sidebar: click **+ New Clock** — modal opens with empty state
5. Modal:
   - Set Clock Name = "Sound Test", Color = pick green
   - Filters tab: pick Sound Code = (any category that has songs),
     BPM 100–130. Watch "X Songs Available" update live.
   - Click **Add** — slot appears as an arc on the circular face
   - Click **Add** again — second arc appears
   - Click an arc → it highlights + the validation strip shows "✓ N
     slots"
   - Switch Colorize-by → Sound Code. Arcs recolor.
   - Click **OK** — modal closes, sidebar shows "Sound Test"
6. Auto Schedule grid: click today × current-hour cell → assign "Sound
   Test"
7. F9 → Studio → **Start Scheduler**
8. Watch the deck auto-advance through the new clock's filter-driven
   songs. Now Playing badges should reflect the slot type.
9. Quit cleanly. Inspect `clock_slots` for the saved row:
   ```sql
   SELECT slot_type, filter_json, minute_position
     FROM clock_slots
     WHERE clock_id = (SELECT id FROM clocks WHERE name = 'Sound Test');
   ```
   Each row should have a JSON filter spec with the BPM range you set.

### Known gaps

- **Era / vocal columns on `songs`**: the filter spec includes
  `era` + `vocal` but the songs table may not have those exact column
  names yet — filters that target them will silently match nothing
  (or all). Sound Code (= category name) and BPM range work.
- **Specific artist filter** uses a name-fallback when the dialog stores
  artist NAME in `ref_text` (since `specific_artist_id` is INTEGER and
  there's no `artists` table normalized yet). Picker handles both
  paths; UI side, choosing an artist works but won't strict-validate.
- **Color picker** uses `QColorDialog` which is a Qt-native modal.
  Looks slightly out-of-theme on Windows; acceptable for now.
- **Songs Found list double-click → add**: not wired yet. User has to
  click Add explicitly. Phase polish.

---

— Claude
