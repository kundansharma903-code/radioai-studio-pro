# RadioAI Studio Pro v2.0 — Codex Guide

## Project Overview
Professional radio automation software for KISS FM 91.5 / FCP Radio, Jaipur, India.
Modeled on Jazler SOHO. Built with **PyQt6 (pure native widgets)** — NO HTML, WebView, Flask, or JavaScript anywhere.

## How to Run
```
cd E:\RadioAI_v2
py main.py
py main.py --debug        # verbose logging
```

## Database
- **Location**: `%LOCALAPPDATA%\RadioAI\radioai.db`  (e.g. `C:\Users\hp\AppData\Local\RadioAI\radioai.db`)
- 33 tables, 395 songs, WAL mode
- Schema: `database/schema.sql` — non-destructive (IF NOT EXISTS)
- Seeds: `database/seeds.sql` — INSERT OR IGNORE only
- Manager: `py database/db_manager.py --verify`

## Audio Engine
- **Library**: BASS via `pybass3` (not python-vlc)
- **License**: Evaluation DLL bundled in pybass3 — **development use only**
- **Production**: Purchase commercial license from https://www.un4seen.com before any broadcast/commercial use
- `bass_init()` called once in `main.py`; `bass_free()` called on exit
- All engines (AudioEngine, StitcherEngine, SweeperEngine) share the same BASS output device

## Key Architecture
| Layer | File | Purpose |
|---|---|---|
| Constants | `core/constants.py` | All colors, paths, magic numbers |
| Database | `core/database.py` | Thread-safe singleton, all SQL here |
| Settings | `core/settings.py` | Singleton cache of settings table |
| Audio | `core/audio_engine.py` | PyQt6 QObject + VLC, 250ms poll |
| Scheduler | `core/scheduler.py` | 2-hour Jazler SOHO queue builder |
| AutoScheduler | `core/auto_scheduler.py` | Clock → playlist queue |
| AI Scheduler | `core/ai_daily_scheduler.py` | Midnight generation, writes ai_daily_log |
| Stitcher | `core/stitcher_engine.py` | pydub pre-mix, single VLC output |
| Sweeper | `core/sweeper_engine.py` | Overlay VLC player, timed trigger |
| Style | `assets/style.qss` | Global dark QSS theme |
| Main window | `ui/main_window.py` | 1920×1080 shell (design canvas); older 1440×900 screens letterbox inside |
| Entry point | `main.py` | Logging→DB→Settings→QApplication→Window |

## Design Colors
```
BG_DARK      = #070812    (root background)
BG_PANEL     = #0a0b18    (side panels, header, statusbar)
BG_CARD      = #0e1020    (cards, list items)
BG_ELEVATED  = #131626    (elevated surfaces)
BORDER       = #1c1f38
TEXT_PRI     = #f1f5ff    (primary text)
TEXT_SEC     = #8891b8    (secondary text)
TEXT_MUTED   = #454d6d    (disabled / hints)
CYAN         = #06b6d4    (primary accent — waveform, progress)
PURPLE       = #8b5cf6    (navigation, categories)
GREEN        = #10b981    (playing, AUTO active, status OK)
AMBER        = #f59e0b    (breaks, warnings, next break countdown)
RED          = #f43f5e    (error, MIX point, stop)
```

## Figma Design Reference

Always read designs from:
File: `7oN9K61g94wKx3nu44KKDF`
Name: RadioAI — Control Panel PREMIUM
URL: https://www.figma.com/design/7oN9K61g94wKx3nu44KKDF

### Screen → Node ID
| Screen                | Node ID |
|-----------------------|---------|
| Control Panel         | 5:2     |
| Songs Library         | 12:2    |
| Spots & Commercials   | 35:2    |
| Scheduling            | 50:2    |
| Main Auto Schedule    | 161:2   |
| Clock Editor          | 165:2   |
| AI Magic              | 170:2   |
| Spots AI Monitor      | 174:2   |
| Studio v3 (Premium)   | 312:2   |

Studio v3 lives on the **Studio Screens v3** page (frame "Studio v3 — Premium Jazler Style"). The earlier `182:2` Single Deck mapping is superseded — do not fetch it.

URL pattern: `https://www.figma.com/design/7oN9K61g94wKx3nu44KKDF?node-id=<node-id>` (use hyphen form, e.g. `5-2`).

### Workflow before building any screen
1. `get_design_context(fileKey, nodeId)` — fetch frame structure, child nodes, sizes
2. `get_screenshot(fileKey, nodeId)` — fetch the visual reference (always download with curl)
3. Read sub-nodes if the response is too large (sparse metadata mode)
4. Build PyQt6 matching the design exactly — pure native widgets, no HTML/WebView
5. Compare result with screenshot; iterate until pixel-aligned

### Studio v3 (312:2) layout reference — 1920×1080
- HEADER (1920×72): Logo + Wordmark stack + Active Station + 3 status pills + Control Panel + Settings
- MASTER STRIP (1920×96): NowPlayer 836w · NextChip 200w · ControlCluster 296w · LevelMeters 80w · AnalogClock 80w · Wordmark 320w
- BODY (1920×820):
  - LEFT (380w): Up Coming queue (5 rich cards + footer)
  - CENTER (720w): Libraries (7 type tiles + Action Stack + Songs table + Filter + Category)
  - RIGHT-TOP (420w + 320w): Instant Jingles · History
  - RIGHT-BOTTOM (420w + 320w): Next Break · RDS · Problems trio
- BOTTOM TRANSPORT (1920×80): Loaded total · ▶/■ · slider · AutoPlay · 6-button cluster

Older premium screens (Hub, Playlists, AutoSchedule, ClockEditor, PlaylistEdit) still hardcode 1440×900 and render top-left-anchored inside the larger 1920×1080 MainWindow stack — visually correct, just letterboxed.

### Studio v3 build chain (Plan A — 9 disciplined commits)
Built incrementally against Figma 312:2, commits `2e706eb..3368497`:
Step 1 `2e706eb` Header · Step 2 `f6efe30` Master strip · Step 3 `cbbda7c` Up Coming · Step 4 `f11ac98` Libraries · Step 5 `928684c` Instant Jingles · Step 6 `525841e` History · Step 7 `4f3a83b` Next Break/RDS/Problems · Step 8 `9f5af52` Bottom Transport · Step 9 `3368497` integration cleanup. Legacy `ui/studio_legacy.py` (2265 lines) retained as rollback insurance until on-air smoke verification.

## Build Order for Screens
1. `ui/screens/studio.py` — main broadcast screen (3-panel layout)
2. `ui/screens/music_library.py` — songs table, cue editor
3. `ui/screens/clock_editor.py` — 24×7 grid + slot editor
4. `ui/screens/campaigns.py` — spots/ads manager
5. `ui/screens/settings.py` — all settings forms
6. `ui/screens/ai_dashboard.py` — AI schedule status + logs

## VLC Thread Safety
VLC EndReached callback fires from VLC thread.
NEVER call Qt from inside a VLC callback.
Pattern used in AudioEngine:
```python
_song_finished = pyqtSignal()   # emitted from VLC thread
# connected to _on_song_finished_main() → runs on Qt main thread
```

## Database execute() compat
`auto_scheduler.py` and `ai_daily_scheduler.py` call `self.db.execute(sql, params)`.
This is implemented on `Database` as a compat method:
- SELECT/PRAGMA/WITH → returns list of rows
- INSERT/UPDATE/DELETE → commits and returns []

## Destructive operation protocol — DO NOT SKIP
Caused a real incident on 2026-05-04 (deleted 15 campaigns + 791 schedule rows
via a malformed `LIKE '__%'` pattern that matched all rows ≥2 chars long).

**Rules for any DELETE / UPDATE / DROP against a shared table:**
1. Never use `LIKE` patterns on names/descriptions for cleanup queries.
   Use `WHERE id IN (…)` or `WHERE name = '…'` (exact match) instead.
2. If `LIKE` is unavoidable, escape the pattern: `LIKE 'foo\_%' ESCAPE '\'`
   so `_` is treated as a literal underscore.
3. Always run a `SELECT COUNT(*)` with the same `WHERE` clause first.
   Show the count and a sample of matched rows. Get explicit user
   confirmation before the destructive op.
4. Wrap the destructive op in `BEGIN TRANSACTION;` … `COMMIT;`. For multi-row
   cleanup, prefer a SQL file the user can review; pipe it through `sqlite3`
   without a trailing `COMMIT;` for a dry-run, then re-run with `COMMIT;`
   appended after approval.
5. Tables with hand-cleaned cascade (no `ON DELETE CASCADE`) — `campaigns`,
   `songs`, `jingle_pads`, `sweepers`, `jingles` — must use the dedicated
   `db.delete_*()` methods, never raw `DELETE FROM`.

## Jazler SOHO Lessons (from manual)
1. Final Log is king — never re-schedule what's been played
2. 2-hour pre-load: queue built for next 2 hours, refreshes automatically
3. Selection Randomness=0 means strict rules (7-day song gap, 3-day slot gap)
4. Mix point triggers crossfade — not song end
5. Clock slots cycle continuously through the clock's slot list
6. AI pre-built schedule takes priority over real-time clock selection
7. Sweepers overlay the song (separate VLC player), not replace it
8. Stitcher pre-mixes "Coming Up Next" block into one WAV before playback
