# MORNING BRIEFING 5 — Scheduling rebuild to Jazler reference (2026-05-05)

> 3-commit overnight that swung Hub / Auto Schedule / Clock Editor away
> from the older Figma nodes (50:2 / 161:2 / 59:2) onto the actual
> Jazler reference images (225:3 / 225:4 / 225:5). Same data layer, new
> operator-familiar surface.

---

## TL;DR

**Hub** is now a 7-tile nav grid + body-level Studio launcher (per ref
225:3). All decoration removed: status badges, week matrix, separation
rules, AI Insight panels.

**Auto Schedule** keeps the 24×7 grid; SET ▶▶ button is now red, tab
order swapped to Specific Days first, modal launch dispatch hook
ready.

**Clock Editor** is a paradigm rebuild:
- Modal QDialog (not full screen) — Cancel / OK exit
- Filter-based slot definition (Sound Code / Era / Vocal / Year /
  Priority / BPM ranges) with live "X Songs Available · avg duration"
- 60-minute circular clock face visualization with slot arcs
- 5 slot-type icons (Song / Jingle / Spot / Voice Track / Sweeper)
- 3 sub-tabs (Filters / Song Tracks / Artists) for slot content source
- Colorize-by Slot Type or Sound Code

**Tests: 142/142 passing** (started rebuild at 136; +6 net new). App
boot clean. Phase B + D + Studio audio still verified working.
**Branch: `native-pyqt6`** — pushed through `aea817b`.

## Commit ledger

```
0e18a4e  feat: Scheduling Hub matches Jazler ref 225:3 — 7-tile nav
                   grid + Studio body launcher
8eaa407  fix:  Auto Schedule polish + modal Clock Editor wiring per
                   ref 225:4
aea817b  feat: Clock Editor rebuilt to Jazler ref 225:5 — modal dialog
                   + filter-based slots + circular 60-min face +
                   colorize-by
```

## Key behaviour changes

### What's gone
- `ui/clock_editor.py` (full-screen, 1300+ lines) — deleted
- `ui/scheduling_hub.py` — stripped from ~600 lines to ~370
- 5 status pills + LIVE timestamp + week matrix + AI Insight + song
  separation rules panels — all gone from the Hub
- Slot-type pills + horizontal timeline + per-type property forms — gone
  from Clock Editor (replaced by filter-driven model)
- `pick_next_song` legacy wrapper — still there but its consumers can
  switch to `pick_next_item` directly

### What's new
- `ui/dialogs/clock_editor_dialog.py` — modal, ~720 lines including
  `_CircularClockFace` custom QPainter widget
- `ui/scheduling_hub.py::_NavTile + _StudioLauncher` — minimal tile +
  body launcher card
- `clocks` columns: comments, color, backup_song_filter,
  loop_cycle_enabled, show_only_descriptions
- `clock_slots` columns: filter_json, specific_song_id,
  specific_artist_id, minute_position
- `SchedulerEngine._songs_matching_filter_json(spec_json)` +
  `count_songs_matching_filter(spec_json)` — Jazler-style filter spec
  resolver
- `MainWindow._open_clock_editor_modal()` — single dispatcher;
  pre-loads selected clock from Auto Schedule, refreshes that screen
  on close

### Wiring

```
Control Panel → Scheduling card → Hub
  Hub → Main Auto Schedule tile → Auto Schedule
  Hub → Final Log / Force Clocks / Playlists / Log Viewer / Rebroadcast
        / RDS tiles → corresponding screens (existing)
  Hub body → ▶ OPEN STUDIO card → Studio (F9 also works)

Auto Schedule sidebar:
  + New Clock          → create empty + open modal
  Clock row click      → select
  Clock row dbl-click  → open modal pre-loaded with that clock
  SET ▶▶ button         → open modal pre-loaded with selected clock
  Duplicate Clock      → duplicate row (via DB), refresh
  Delete Clock         → delete (with confirm)

Modal Clock Editor (ref 225:5):
  Filters tab:  pick Sound Code / Era / Vocal / Year / Priority / BPM
                ranges. Live "X Songs Available" count.
                Click Add → arc drawn on circular face.
  Song Tracks tab:   search song → click Add → exact-song slot
  Artists tab:       pick artist → click Add → random-from-artist slot
  Colorize-by:       Slot Type or Sound Code
  OK:                save clock + slots
  Cancel:            dismiss
```

## How to test (manual smoke)

Step-by-step in `NIGHT_LOG_5.md`. Quick version:

1. `py main.py` → Control Panel → Scheduling card → Hub
2. Hub shows 7 tiles + Studio launcher (no badges, no week matrix)
3. Click Main Auto Schedule → grid loads
4. Click **+ New Clock** → modal opens
5. In modal: name it, pick a category, set BPM 100–130, click **Add**
   twice. Watch arcs appear on the circular face.
6. **OK** → modal closes, new clock in sidebar
7. Assign that clock to today × current hour
8. F9 → Studio → **Start Scheduler** → songs from your filter play

## Known issues

- **Era / vocal columns**: the filter spec covers them but `songs`
  doesn't necessarily have those exact column names. Filters that
  target them will match 0 songs — that's expected silent behaviour
  pending a `songs` schema audit. Sound Code + BPM work.
- **Artist picker**: stores artist NAME via `ref_text` (not ID) since
  there's no normalised `artists` table yet. Works but isn't FK-clean.
- **Color picker**: native `QColorDialog` — slightly out-of-theme.
- **Songs Found list double-click → add**: not wired (user clicks Add
  explicitly).
- **Two leaked test clocks** in DB (`E2E Pipeline Test`,
  `Mutations Test`, `Filter Persist Test`) from prior test runs that
  hit the FK guard before cleanup landed. Delete via Auto Schedule
  sidebar if you want a clean list.

## Next session recommendation

Now that the Jazler-faithful surface is in place, **Phase E (Anthropic
Claude integration)** is the right next step. The hooks:

1. **Modal Clock Editor → AI Auto-Build** — given the current filter
   spec + a target hour-of-day, ask Claude to suggest a balanced slot
   sequence. Insert results as slots.
2. **Hub → Generate Today's Log** (currently a Phase E toast in the
   Final Log screen). Claude composes from clocks + auto_schedule +
   scheduling_rules.
3. **Auto Schedule → Optimize Week** — surface gaps/overlaps and
   suggest fills.
4. **Clock Editor → "27 Songs · avg 3:14"** indicator — Phase E layer
   could augment with rotation-health flags ("Last week this filter
   played 4 songs heavily").

Spec needs to land first: Anthropic Claude prompt schema + JSON
response shape that the UI consumes. Once that's settled, wiring is
straightforward across these 4 hooks.

— Claude
