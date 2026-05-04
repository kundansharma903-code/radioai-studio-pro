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
| Status (2026-05-04) | Phase D complete. Studio + scheduler production-ready. "Lagao chod do" capable. |

## 2. Tech stack

| Layer | Tech |
|---|---|
| UI | **PyQt6 native** (no HTML / WebView / Flask / JS — strict) |
| Audio | **pybass3** (BASS); evaluation DLL bundled, commercial purchase before broadcast |
| DB | **SQLite** with WAL, thread-local connections, singleton pool |
| AI | **Claude API** (integration deferred to Phase E) |
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
Audio engine pkg  :  E:\RadioAI_v2\core\audio\          (Phase A — multi-channel)
Scheduler pkg     :  E:\RadioAI_v2\core\scheduler\      (Phase D3+)
Database layer    :  E:\RadioAI_v2\core\database.py
Legacy engines    :  E:\RadioAI_v2\core\{audio,sweeper,stitcher,instant_jingle}_engine.py
Schema            :  E:\RadioAI_v2\database\schema.sql
Seeds             :  E:\RadioAI_v2\database\seeds.sql + seeds_instant.py
Recovery script   :  E:\RadioAI_v2\database\recovery_campaigns.sql
Screenshots       :  E:\RadioAI_v2\screenshots\
Design refs       :  E:\RadioAI_v2\design_refs\          (figma_*.png in .gitignore)
Tests             :  E:\RadioAI_v2\tests\                (pytest under conftest.py)
Project docs      :  E:\RadioAI_v2\CLAUDE.md, FIGMA_TO_PYQT6.md
```

## 4. Reference / external

| | |
|---|---|
| Figma file | `7oN9K61g94wKx3nu44KKDF` (RadioAI — Control Panel PREMIUM) |
| Figma URL | `https://www.figma.com/design/7oN9K61g94wKx3nu44KKDF?node-id=<id>` (use hyphen form, e.g. `5-2`) |
| GitHub repo | `github.com/kundansharma903-code/radioai-studio-pro` |
| Active branch | `native-pyqt6` (canonical — DO NOT touch `main`) |
| Local git | E:\RadioAI_v2\ IS a git repo, connected to remote, push proactively after every phase day |

## 5. Built screens

| Screen | Figma node | File |
|---|---|---|
| Control Panel | `192:2` | `ui/control_panel.py` |
| Songs Library | `212:2` | `ui/songs_library.py` |
| Instant Jingles | `44:688` | `ui/instant_jingles.py` |
| Spots & Commercials Library | `35:2` | `ui/spots_commercials.py` |
| **Studio Single Deck** | **`182:2`** | **`ui/studio.py`** (Phase D — broadcast operator workstation) |

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
| Audio Cue Editor | `30:2` | `ui/dialogs/audio_cue_editor_dialog.py` (Phase 5 complete + B1 wired) |

## 7. Premium widget library

Located in `ui/widgets/`, exposed via `ui/widgets/__init__.py`:

| Widget | Purpose |
|---|---|
| `PremiumCard` | gradient + multi-shadow card surface |
| `GlowingButton` | premium gradient button with outer glow |
| `StatCard` | big-number stat with accent bar |
| `WaveformWidget` | small decorative waveform (Studio panels). `set_auto_animate(bool)` lets external code drive position (added in B2). |
| `PremiumTable` | styled QTableWidget subclass |
| `PremiumBadge` | rounded pill badge |
| `PictorialIcon` (`IconType` enum) | custom-drawn line icons (no emoji) |
| `LiveIndicator` | pulsing dot with glow |
| `CategoryPill` | color-coded mini-badge |
| `LiveClock` | mono auto-updating clock |

Token constants live in `ui/widgets/_tokens.py` — colors, font helpers, `rgba()`, `qcolor()`.

## 8. Audio + Scheduler packages (Phase A + D3)

### `core/audio/` — multi-channel BASS engine

```
core/audio/
   __init__.py           re-exports
   _bass.py              private DLL singleton + ctypes argtypes + SYNCPROC
   channels.py           Channel dataclass + state vocabulary
   engine.py             AudioEngine(QObject)
   exceptions.py         AudioEngineError / ChannelError / FormatError
   tags.py               Tags dataclass + TagReader (mutagen wrapper)
```

**`AudioEngine` public API:**
- Lifecycle: `load_file(path, loop=False)`, `cleanup`, `cleanup_all`
- Playback: `play`, `pause`, `resume`, `stop`
- Position: `seek_to_ms`, `get_position_ms`, `get_duration_ms`
- Volume: `set_volume`, `get_volume`, `fade_volume_to`
- Probe: `probe_duration_ms(path)` — read duration without persistent channel
- Queries: `is_playing`, `get_state`, `active_channels`, `get_active_channels` (filtered to playing/paused), `is_fading`, `get_channel_info`
- Signals: `position_changed(cid, ms)`, `playback_ended(cid)`, `error_occurred(cid, msg)`, `channel_state_changed(cid, state)`
- Constants: `MAX_CHANNELS=8`, `POSITION_UPDATE_MS=100`

**State vocabulary:** `loaded` → `playing` → `paused` → `playing` → `stopped` / `ended` / `error`.

**Lifecycle contract:** caller MUST invoke `cleanup_all()` before `bass_free()`. Engine intentionally does NOT implement `__del__` (Python GC ordering unreliable with Qt teardown). MainWindow's `closeEvent` + `aboutToQuit` BOTH call `_cleanup_engine()` (idempotent belt-and-suspenders). Scheduler is stopped FIRST (silence event source), then audio cleanup.

### `core/scheduler/` — background broadcaster (Phase D3+)

```
core/scheduler/
   __init__.py           re-exports
   engine.py             SchedulerEngine(QObject) on a QThread
   events.py             EventType enum + ScheduledEvent dataclass
```

**`SchedulerEngine` public API:**
- Lifecycle: `start()`, `stop()`, `is_running()`, `tick_count` property
- Signals: `spot_due(campaign_id)`, `song_auto_advance` (declared, reserved for Phase E), `break_approaching(seconds)`, `next_break_in(seconds)`, `schedule_reloaded`, `error_occurred(msg)`, `started`, `stopped`
- Constants: `DEFAULT_TICK_INTERVAL_MS=1000`, `SPOT_TOLERANCE_S=30`, `BREAK_WARN_S=30`

**Threading model:** runs on its own QThread, ticks at 1Hz (configurable for tests), emits signals via QueuedConnection auto-marshal back to UI consumers on the main thread. Day-rollover detection reloads `campaign_schedule` + clears the dedupe set. `_dispatch_due_events` is per-tick error-isolated.

**⚠ Module-package collision:** `core/scheduler.py` (legacy file from before Phase D3) is shadowed by the package. The legacy `Scheduler` class wrapping `AutoScheduler` is dead/unreachable. Recommended cleanup: delete `core/scheduler.py` in a prep commit. Legacy `core/auto_scheduler.py` lingers as reference for slot-type semantics; not consumed by anything live.

### Legacy engines (still in `core/*.py`)

- `core/audio_engine.py` — **legacy single-deck `AudioEngine` class.** Untouched throughout Phase A + B + D. Owns `bass_init()` / `bass_free()` (the canonical, single-process BASS device). Its single-deck class is dead code (no UI wires it); a future phase may delete it once Studio is the source of truth for deck playback.
- `core/instant_jingle_engine.py` — **rebased on `core.audio.AudioEngine` in Phase B4.** Now a thin adapter: `InstantJingleEngine(engine=audio_engine, parent=...)`. Maps `pad_id → channel_id`. Polyphony cap (8) filtered to JINGLE channels only.
- `core/sweeper_engine.py` — overlay player. Standalone, not wired to live UI.
- `core/stitcher_engine.py` — sequential pre-mixer. Standalone.

## 9. Database tables (33+ tables)

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
- `campaign_schedule` (campaign × day × break_time, added `priority` in Phase 4.2b) — **read by SchedulerEngine.**
- `spot_schedules` (Studio "next break" countdown)

**Scheduling / AI / Logging:**
- `clocks`, `clock_slots`, `force_clocks`, `auto_schedule` — **populated, NOT yet edited by UI.** Phase F will build the Clock Editor + Auto Schedule screens. Existing rows: clocks=26, clock_slots=291, auto_schedule=88, force_clocks=0.
- `final_logs`, `final_log_entries`
- `broadcast_log` — **scheduler-triggered spots write here in Phase D4.** Format: entry_type IN ('song','spot','jingle','sweeper','stitcher'), `was_manual=0` for scheduler-driven, `was_manual=1` reserved for explicit operator decisions. Manual deck plays from Studio do NOT log (audition only).
- `ai_daily_log`, `ai_decisions`, `ai_run_steps`, `ai_schedule_status`, `ai_schedule_warnings`

**Settings / misc:**
- `settings` (key/value), plus a few legacy tables

**Migrations live as `_ensure_*_columns()` methods on `Database`** — idempotent, safe to call on every connection bootstrap. Pattern: `PRAGMA table_info()` check → `ALTER TABLE ADD COLUMN IF NOT EXISTS`-style guard.

## 10. Coding conventions (project-specific)

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
- **Audio: use AudioEngine via Option C DI** — `MainWindow` constructs the singleton, passes to UI consumers via constructor. Each UI surface owns its own channel(s); cleanup is per-channel on dialog close, MainWindow does `cleanup_all()` on app close. Avoid `core.audio_engine` legacy class — use `core.audio.AudioEngine`.

## 11. Performance invariants (custom-paint widgets)

Documented at top of [`ui/dialogs/spot_programming_dialog.py`](ui/dialogs/spot_programming_dialog.py), [`ui/dialogs/audio_cue_editor_dialog.py`](ui/dialogs/audio_cue_editor_dialog.py), and [`ui/studio.py`](ui/studio.py):

1. **Single-source scrolling** — never wrap a custom-paint widget in a nested `QScrollArea` when BaseDialog already provides the outer scroll. Nested scrolls + tall fixed-size grandchild trigger Qt size-negotiation loops that look like a freeze.
2. **`paintEvent` clips to `event.rect()`** — compute first/last visible row from the dirty rect; don't paint thousands of cells unconditionally.
3. **`mouseMoveEvent` uses bounded `self.update(rect)`** — never bare `self.update()`. Compute the dirty rect from old + new state.
4. **No `setMouseTracking(True)` unless needed** — only enable if you specifically need hover events.
5. **No DB calls or self.update() inside paintEvent** — recursion / paint-storm guard.
6. **No `setFixedSize` on heights > 2000px** — use `setFixedHeight` only and let width follow the parent layout.

## 12. Past incidents (DO NOT REPEAT)

### Incident 1 — `DELETE FROM ... WHERE name LIKE '__%'` nuked 15 campaigns (2026-05-04)

`'__%'` matches any string ≥2 chars (SQL `_` is a single-char wildcard). Recovered via [`database/recovery_campaigns.sql`](database/recovery_campaigns.sql). Resolution + guardrails recorded in `CLAUDE.md` under "Destructive operation protocol — DO NOT SKIP".

**Rule: never DELETE/UPDATE with `LIKE` patterns on shared tables.** Use `WHERE id IN (...)` or exact `name = '...'`. If `LIKE` is unavoidable, escape with `ESCAPE '\'`. Always `SELECT COUNT(*)` first, show user, get confirmation.

### Incident 2 — Spot Programming dialog freeze (2026-05-04)

Dialog construction hung the app. Root cause: nested `QScrollArea` (BaseDialog outer with `setWidgetResizable=True` + my inner) + 4064px fixed-size grandchild → Qt layout-storm. Resolution: removed inner scroll (Fix B), added `event.rect()` clipping (Fix A), bounded hover updates (Fix C). Performance invariants now documented at top of file.

### Incident 3 — Phase D4 Studio crash on first scheduler-triggered spot

Two bugs caught during D4 smoke test before reaching production:
- Module-level `import os` missing in `ui/studio.py` → `_on_scheduler_spot_due` crashed at `os.path.exists(...)` check.
- `chosen.get("filename")` on a `sqlite3.Row` (Row supports `__getitem__` + `.keys()` but NOT `.get`) → AttributeError under a Qt slot exit-127'd the process.

Both fixed in the same D4 commit. Defensive lesson: wrap Qt slots in try/except + traceback logging when they touch DB rows or filesystem; sqlite3.Row needs `in row.keys()` checks, not `.get()`.

## 13. Working protocol — followed throughout this project

1. **Read FIGMA_TO_PYQT6.md** before each new screen
2. **Get Figma design first** — `mcp__5cba59a6-7186-467e-9585-0c4139665053__get_screenshot` (and `get_design_context` for token data when needed; downloads tend to be too large — use ToolSearch to load tool, then targeted node fetches only)
3. **Plan + ask questions before coding** — don't blindly accept user spec; reality-check schema, existing widgets, integration points; push back on technical calls when warranted
4. **Phase the build with screenshot checkpoints** — typical 3-phase pattern (skeleton → interaction → integration)
5. **Wait for user visual approval at each checkpoint** — do not proceed without explicit "approved"
6. **Iterate visual gaps** — small fixes inline, then re-screenshot
7. **Real DB integration always** — no mocks, no fake data unless seeded with intent
8. **Acknowledge stubs honestly** — flag known TBDs in handoff

## 14. Known stubs and tech debt

**Cleared in Phase A + B + D:**
- ✅ Audio Cue Editor PREVIEW buttons (B1)
- ✅ Audio Cue Editor Play/Stop transport (B1)
- ✅ Songs Library row preview (B2)
- ✅ Spots Now Airing real countdown (B3)
- ✅ Instant Jingles rebased on AudioEngine (B4)
- ✅ Studio screen UI built (D1)
- ✅ Studio manual playback (D2)
- ✅ Scheduler architecture (D3)
- ✅ Spot triggering + broadcast_log persistence (D4)
- ✅ Song queue + auto-advance + loop / stop-next / spot-resume (D5)
- ✅ History list DB-driven, status bar pills state-driven (D6)
- ✅ MainWindow lifecycle hook (B5)

**Remaining stubs / future work:**

- **Studio Validate button** — visual stub, no checks (Phase F4 / Phase E)
- **Studio AI Optimise button** — visual stub, Phase E AI integration
- **Status bar AI Active pill** — stays dim, marked as Phase E placeholder
- **AI Insights panel** — hardcoded list with `(placeholder — Phase E AI integration)` footer marker
- **Edit Categories Save bug** — investigation deferred
- **Per-file legacy column duplication on `songs`:**
  - `intro_point_ms` (canonical) vs `intro_end_ms` vs `intro_time` (legacy)
  - `mix_point_ms` (canonical) vs `mix_point` (legacy)
  - `hook_in_ms` / `hook_in_time`, `hook_out_ms` / `hook_out_time`, `outro_point_ms` / `outro_time`
  - Phase 5+ writes only to `_ms` columns. Cleanup is a future migration phase.
- **Scheduling UI screens** — Phase F (this is what's next)
- **Crossfade / ducking / EQ / multi-output routing** — Phase C
- **Songs Library Detail panel tabs** — clicking the tabs doesn't switch content; visual only. Tab system not yet wired.
- **`core/scheduler.py` legacy file** — shadowed by the package. Recommend delete in a prep commit before Phase F build starts.

## 15. User preferences (collected from session history)

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
- Prefers small day-by-day phase building with explicit Q&A before each day
- Each phase day = commit + push (commit policy enforced)

## 16. Test surface (under pytest)

`tests/` directory with `conftest.py` providing shared fixtures:
- `qapp_args` — pytest-qt Qt app config (-platform minimal)
- `_bass` (autouse) — bass_init/free at session boundaries
- `engine` — fresh AudioEngine per test
- `test_song_path`, `test_long_song_path`, `test_song_with_db_dur` — real DB songs

**74 tests passing** (`pytest -m "not slow"`: 73, plus 1 slow soak):

| File | Tests | Phase |
|---|---|---|
| `test_engine_load_play.py` | 9 | A1 |
| `test_engine_position.py` | 14 (incl 5 parametrized) | A2 |
| `test_engine_multi.py` | 10 | A3 |
| `test_tags.py` | 7 | A4 |
| `test_engine_polish.py` | 15 (10 polish + 5 B4 primitives) | A5 + B4 |
| `test_engine_lifecycle.py` | 5 | B5 |
| `test_scheduler_lifecycle.py` | 5 | D3 |
| `test_scheduler_dispatch.py` | 5 | D4 |
| `test_studio_eos_paths.py` | 4 | D6 |

Test runner:
```
pytest                  # all tests including slow soak
pytest -m "not slow"    # dev default — skip soak (~12s)
pytest -m slow          # soak only (100-cycle stress)
```

`pytest-qt 4.5+` and `pytest 9.0+` required (in `requirements-dev.txt`).

---

## 17. GitHub repository

- Repo: `github.com/kundansharma903-code/radioai-studio-pro`
- Active branch: `native-pyqt6` (canonical — DO NOT touch `main`)
- Local path: `E:\RadioAI_v2\` is initialized + remote-connected; push proactively after every phase day.

### Recent commit history (most recent at top)

- `7e9cde3 docs: Phase D complete — Studio + scheduler + continuous play`
- `f203715 feat: Phase D6 — polish + Phase D close-out`
- `e1cf756 feat: Phase D5 — song queue + auto-advance + loop / stop-next / spot-resume`
- `88a0793 feat: Phase D4 — spot triggering + broadcast_log persistence`
- `3d54ff5 feat: Phase D3 — Scheduler engine architecture (background QThread)`
- `f5d15aa feat: Phase D2 — Studio manual playback wired to AudioEngine`
- `fb77b19 feat: Phase D1 — Studio Single Deck UI skeleton (Figma 182:2)`
- `385ee72 docs: Phase B complete — audio engine wired to all existing UI surfaces`
- `de8d4f4 feat: Phase B5 — MainWindow lifecycle hook + per-channel error isolation`
- `5b2da7c feat: Phase B4 — Instant Jingles rebased on AudioEngine (Option A)`
- `83d941a feat: Phase B3 — Spots Now Airing real audio playback`
- `e6603c4 feat: Phase B2 — Songs Library row preview wired to AudioEngine`
- `dfb2e29 feat: Phase B1 — Audio Cue Editor PREVIEW + Play/Stop wired to AudioEngine`
- `893d4ee docs: Phase A complete — multi-channel audio engine production-ready`
- (Phase A1–A5 + B5 marker + many earlier — see `git log` for full history)

**Phase D close-out complete. "Lagao chod do" capability achieved.** Operator can open Studio, double-click a song, walk away — scheduler triggers ad breaks at scheduled times, spots air with real broadcast_log persistence, music auto-advances between spots, continuous broadcast.

### How to use GitHub from a new session

- Push proactively after every phase day. `git add .` is now safe (`.claude/worktrees/` is in `.gitignore`).
- Always include a `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` trailer.
- Use specific-file `git add` if uncertain about untracked content; never `git init` or touch `main`.
- For Figma reference downloads: write to `design_refs/figma_*.png` (now gitignored).
