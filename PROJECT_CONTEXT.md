# RadioAI Studio Pro v2.0 — Project Context

> Master reference for any new Claude Code session resuming work.
> Read this **first**, then `CURRENT_TASK_STATE.md`, then start work.

---

## 1. Product

| | |
|---|---|
| Name | RadioAI Studio Pro v2.0 |
| Owner | Kavish — KISS FM 91.5 (FCP Radio), Jaipur |
| Purpose | Professional radio automation modeled on Jazler SOHO |
| Audio | Live broadcast — production-bound |

## 2. Tech stack

| Layer | Tech |
|---|---|
| UI | **PyQt6 native** (no HTML / WebView / Flask / JS — strict) |
| Audio | **pybass3** (BASS); evaluation DLL bundled, commercial purchase before broadcast |
| DB | **SQLite** with WAL, thread-local connections, singleton pool |
| AI | **Claude API** (integration deferred to later phase) |
| Fonts | Inter Variable + Roboto Mono (loaded at startup from `assets/fonts/`) |
| Style | Central QSS at `assets/premium.qss` |

## 3. Paths

```
Project root      :  E:\RadioAI_v2\
Database          :  %LOCALAPPDATA%\RadioAI\radioai.db
Settings          :  E:\RadioAI_v2\.claude\settings.json   (bypassPermissions mode)
QSS               :  E:\RadioAI_v2\assets\premium.qss
Fonts             :  E:\RadioAI_v2\assets\fonts\
Premium widgets   :  E:\RadioAI_v2\ui\widgets\
Dialogs           :  E:\RadioAI_v2\ui\dialogs\
Screens           :  E:\RadioAI_v2\ui\
Database layer    :  E:\RadioAI_v2\core\database.py
Audio engines     :  E:\RadioAI_v2\core\{audio,sweeper,stitcher,instant_jingle}_engine.py
Schema            :  E:\RadioAI_v2\database\schema.sql
Seeds             :  E:\RadioAI_v2\database\seeds.sql + seeds_instant.py
Recovery script   :  E:\RadioAI_v2\database\recovery_campaigns.sql
Screenshots       :  E:\RadioAI_v2\screenshots\
Design refs       :  E:\RadioAI_v2\design_refs\   (Figma PNGs + harness scripts)
Project docs      :  E:\RadioAI_v2\CLAUDE.md, FIGMA_TO_PYQT6.md
```

## 4. Reference / external

| | |
|---|---|
| Figma file | `7oN9K61g94wKx3nu44KKDF` (RadioAI — Control Panel PREMIUM) |
| Figma URL | `https://www.figma.com/design/7oN9K61g94wKx3nu44KKDF?node-id=<id>` (use hyphen form, e.g. `5-2`) |
| GitHub branch | `native-pyqt6` (remote: `github.com/kundansharma903-code/radioai-studio-pro`) |
| **Git status locally** | ⚠ **Not a git repo locally** — `E:\RadioAI_v2\` has no `.git` folder. User commits from elsewhere. |

## 5. Built screens

| Screen | Figma node | File |
|---|---|---|
| Control Panel | `192:2` | `ui/control_panel.py` |
| Songs Library | `212:2` | `ui/songs_library.py` |
| Instant Jingles | `44:688` | `ui/instant_jingles.py` |
| Spots & Commercials Library | `35:2` | `ui/spots_commercials.py` |

## 6. Built dialogs

| Dialog | Figma node | File |
|---|---|---|
| BaseDialog (foundation) | — | `ui/dialogs/base_dialog.py` |
| Add New Song | `28:2` | `ui/dialogs/add_new_song_dialog.py` |
| Add Artist | `218:2` | `ui/dialogs/add_artist_dialog.py` |
| Find Artist | `218:46` | `ui/dialogs/find_artist_dialog.py` |
| Mass Import | `112:2` | `ui/dialogs/mass_import_dialog.py` |
| Edit Categories | `32:2` | `ui/dialogs/edit_categories_dialog.py` |
| Confirm Delete (song delete) | custom | `ui/dialogs/confirm_delete_dialog.py` |
| Add Campaign / Edit Campaign | `100:2` | `ui/dialogs/add_campaign_dialog.py` |
| Date Picker | `101:2` | `ui/dialogs/campaign_date_picker_dialog.py` |
| Spot Programming | `102:2` | `ui/dialogs/spot_programming_dialog.py` |
| Audio Cue Editor (Phase 5 in progress) | `30:2` | `ui/dialogs/audio_cue_editor_dialog.py` |

## 7. Premium widget library

Located in `ui/widgets/`, exposed via `ui/widgets/__init__.py`:

| Widget | Purpose |
|---|---|
| `PremiumCard` | gradient + multi-shadow card surface |
| `GlowingButton` | premium gradient button with outer glow |
| `StatCard` | big-number stat with accent bar |
| `WaveformWidget` | small decorative waveform (Studio panels) |
| `PremiumTable` | styled QTableWidget subclass |
| `PremiumBadge` | rounded pill badge |
| `PictorialIcon` (`IconType` enum) | custom-drawn line icons (no emoji) |
| `LiveIndicator` | pulsing dot with glow |
| `CategoryPill` | color-coded mini-badge |
| `LiveClock` | mono auto-updating clock |

Token constants live in `ui/widgets/_tokens.py` — colors, font helpers, `rgba()`, `qcolor()`.

## 8. Database tables (33+ tables)

**Core:**
- `songs` (50 cols after Phase 5-A migration — added `auto_cue`, `normalize`, `bit_depth_32`, `title_field_mode`, `artist_field_mode`, `update_on_play`)
- `categories`
- `jingle_pallets`, `jingle_pads` (added `play_count`, `last_played` in Instant Jingles phase)
- `jingles`, `sweepers`
- `playlists`, `playlist_songs`

**Spots & Commercials:**
- `campaigns` (added `auto_code`, `min_gap_minutes`, `max_per_break`, `availability` in Phase 4.2a)
- `spot_files`
- `break_schedule` (campaign-agnostic timetable)
- `campaign_schedule` (campaign × day × break_time, added `priority` in Phase 4.2b)
- `spot_schedules` (Studio "next break" countdown)

**Scheduling / AI / Logging:**
- `clocks`, `clock_slots`, `force_clocks`, `auto_schedule`
- `final_logs`, `final_log_entries`
- `broadcast_log` (the canonical play log; `entry_type` IN 'song','spot','jingle','sweeper','stitcher')
- `ai_daily_log`, `ai_decisions`, `ai_run_steps`, `ai_schedule_status`, `ai_schedule_warnings`

**Settings / misc:**
- `settings` (key/value), plus a few legacy tables

**Migrations live as `_ensure_*_columns()` methods on `Database`** — idempotent, safe to call on every connection bootstrap. Pattern: `PRAGMA table_info()` check → `ALTER TABLE ADD COLUMN IF NOT EXISTS`-style guard.

## 9. Coding conventions (project-specific)

- **8px grid spacing** — all paddings/gaps multiples of 4 or 8
- **`rgba()` for borders** — never solid hex like `#1c1f38`. Use `rgba(255,255,255,0.06)` for translucent borders.
- **Multi-stop gradients** — never flat colors where Figma shows gradient
- **Premium dark theme palette** — `#070812` root, `#0a0c16` panels, `#0e1020` cards, `#131626` elevated. Accent colors via `_tokens.py` constants (`CYAN`, `PURPLE`, `GREEN`, `AMBER`, `RED`, `PINK`, `TEAL` + `_LIGHT` variants).
- **Custom paint for premium effects** — `QPainter` for anything QSS can't do (multi-layer shadows, color zones, custom icons). No emoji as icons.
- **Letter-spacing on uppercase labels** — `inter(size, weight, letter_spacing=…)`.
- **BaseDialog for all dialogs** — frameless, drag-from-header, adaptive sizing capped at 95%×92% of available screen. Min 640×480.
- **Database singleton** — thread-local connections via `_local.conn`. Never instantiate `Database()` multiple times — always `Database()` returns the same singleton.
- **Don't over-engineer** — bug fix doesn't need refactor; one-shot doesn't need helper. Three similar lines is better than premature abstraction.
- **Default to no comments** — only when WHY is non-obvious. Don't explain WHAT.
- **Audio: use `pybass3`** — `BassStream.CreateFile(False, path.encode("utf-8"), 0, 0, BASS_STREAM_PRESCAN)` + `BassChannel.Play(handle, False)`. Volume via `BASS_ChannelSetAttribute(BASS_ATTRIB_VOL, ...)`. Multiple engines coexist — see `core/audio_engine.py` (deck), `core/instant_jingle_engine.py` (polyphonic pads), `core/sweeper_engine.py`, `core/stitcher_engine.py`.

## 10. Performance invariants (custom-paint widgets)

Documented at top of [`ui/dialogs/spot_programming_dialog.py`](ui/dialogs/spot_programming_dialog.py) and [`ui/dialogs/audio_cue_editor_dialog.py`](ui/dialogs/audio_cue_editor_dialog.py):

1. **Single-source scrolling** — never wrap a custom-paint widget in a nested `QScrollArea` when BaseDialog already provides the outer scroll. Nested scrolls + tall fixed-size grandchild trigger Qt size-negotiation loops that look like a freeze.
2. **`paintEvent` clips to `event.rect()`** — compute first/last visible row from the dirty rect; don't paint thousands of cells unconditionally.
3. **`mouseMoveEvent` uses bounded `self.update(rect)`** — never bare `self.update()`. Compute the dirty rect from old + new state.
4. **No `setMouseTracking(True)` unless needed** — only enable if you specifically need hover events.
5. **No DB calls or self.update() inside paintEvent** — recursion / paint-storm guard.
6. **No `setFixedSize` on heights > 2000px** — use `setFixedHeight` only and let width follow the parent layout.

## 11. Past incidents (DO NOT REPEAT)

### Incident 1 — `DELETE FROM ... WHERE name LIKE '__%'` nuked 15 campaigns (2026-05-04)

`'__%'` matches any string ≥2 chars (SQL `_` is a single-char wildcard). Recovered via [`database/recovery_campaigns.sql`](database/recovery_campaigns.sql). Resolution + guardrails recorded in `CLAUDE.md` under "Destructive operation protocol — DO NOT SKIP".

**Rule: never DELETE/UPDATE with `LIKE` patterns on shared tables.** Use `WHERE id IN (...)` or exact `name = '...'`. If `LIKE` is unavoidable, escape with `ESCAPE '\'`. Always `SELECT COUNT(*)` first, show user, get confirmation.

### Incident 2 — Spot Programming dialog freeze (2026-05-04)

Dialog construction hung the app. Root cause: nested `QScrollArea` (BaseDialog outer with `setWidgetResizable=True` + my inner) + 4064px fixed-size grandchild → Qt layout-storm. Resolution: removed inner scroll (Fix B), added `event.rect()` clipping (Fix A), bounded hover updates (Fix C). Performance invariants now documented at top of file.

## 12. Working protocol — followed throughout this project

1. **Read FIGMA_TO_PYQT6.md** before each new screen
2. **Get Figma design first** — `mcp__5cba59a6-7186-467e-9585-0c4139665053__get_screenshot` (and `get_design_context` for token data when needed)
3. **Plan + ask questions before coding** — don't blindly accept user spec; reality-check schema, existing widgets, integration points; push back on technical calls when warranted
4. **Phase the build with screenshot checkpoints** — typical 3-phase pattern (skeleton → interaction → integration)
5. **Wait for user visual approval at each checkpoint** — do not proceed without explicit "approved"
6. **Iterate visual gaps** — small fixes inline, then re-screenshot
7. **Real DB integration always** — no mocks, no fake data unless seeded with intent
8. **Acknowledge stubs honestly** — flag known TBDs in handoff

## 13. Known stubs and tech debt

**Library — Spots & Commercials:**
- `Break Settings` sidebar button (logs `TBD`, no behavior)
- `Category` / `Priority` / `Day` filter dropdowns (visual only)
- 5 sidebar Reports buttons (visual only — Phase 4.2c-B deferred)
- `Now Airing` strip (no real BASS playback / scheduler integration)
- Detail panel Tabs 2 & 3 ("Break Schedule" / "Play Reports" — placeholder copy)

**Library — Songs:**
- Detail panel tabs (Song Details / Audio Cues / Play History) are visual buttons — clicking doesn't switch tab content. Audio Cues tab is "active" by virtue of being painted that way. Phase 5-A added a temporary "✎ Edit Cues" button below the AI insight box; final placement deferred to Phase 5-C / tab-system phase.

**Audio Cue Editor (Phase 5 in progress):**
- All PREVIEW buttons are stubs (button flashes green + log line, no audio playback)
- Play / Stop transport buttons (left of cue cards) are stubs
- Browse path button is a stub
- "Audio file not found → using stored duration" warning — no toast UI yet, just `log.warning`

**Audio engine integration (cross-cutting):**
- Spot Programming dialog: schedule rows persist to DB but no BASS playback when "applied to live broadcast"
- Audio Cue Editor: PREVIEW paths logged but not wired to pybass3
- Library Now Airing strip: dummy progress bar
- Both Edit Categories Save bug investigation and Now Airing wiring depend on broader audio-engine + scheduler-engine phases

**Per-file legacy column duplication on `songs`:**
- `intro_point_ms` (canonical) vs `intro_end_ms` vs `intro_time` (legacy)
- `mix_point_ms` (canonical) vs `mix_point` (legacy)
- `hook_in_ms` / `hook_in_time`, `hook_out_ms` / `hook_out_time`, `outro_point_ms` / `outro_time`
- Phase 5+ writes only to `_ms` columns. Cleanup is a future migration phase.

**Mass Change Priorities / Set Mode buttons** in Spot Programming sidebar — log `TBD`.

## 14. User preferences (collected from session history)

- Hindi-English mixed communication is fine
- Wants **smart proactive suggestions, not "haan haan" agreement** — push back when technical call is wrong
- Premium quality matters — not "local-looking" icons
- Foundation FIRST before features
- Validate work via screenshot comparison
- Real DB integration (no mocks)
- Pure PyQt6 (no HTML/WebView)
- Wants exact Figma replication, not improvisation (95%+ match is the bar)
- Approves recommended defaults when offered ("go all defaults" pattern)
- Splits long sessions into manageable phases with checkpoints
- Approves destructive ops only after dry-run + explicit confirmation

---

## 15. GitHub Repository

- Repo: `github.com/kundansharma903-code/radioai-studio-pro`
- Active branch: `native-pyqt6`
- Local path: `E:\RadioAI_v2\` — **NOT a git repo locally**; user commits via separate workflow on a different machine

### Recent commit history (relevant — user-side commits)

- Phase 4.2a — Spots Library + Add Campaign dialog
- Phase 4.2b — Date Picker + Spot Programming dialogs (Spots & Commercials group complete)
- Phase 4.2c-A — Edit Campaign feature
- WIP: Phase 5-A — Audio Cue Editor skeleton + waveform + stationary markers
- Phase 5-B — committed to disk locally (drag + cards + sliders + validation), **awaiting user verification**

### How to use GitHub from a new session

- A new Claude Code session can `git clone` to a temp path **for inspection only** if it needs to look at remote history:
  ```
  git clone https://github.com/kundansharma903-code/radioai-studio-pro.git <temp_path>
  ```
- **DO NOT** modify or push to the remote without explicit user approval.
- **DO NOT** `git init` the local `E:\RadioAI_v2\` directory — would diverge from the canonical user-side repo.
- For diff inspection, the user runs `git log` / `git diff` on their separate dev machine.
