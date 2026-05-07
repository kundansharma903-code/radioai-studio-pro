# RadioAI Studio Pro — Session Handover (2026-05-07, Part 2)

> Read this end-to-end before touching any file. The previous session
> shipped 19 commits across the sweeper ecosystem, Studio fixes, station
> rebrand refactor, and the new Play Report feature. This handover
> captures every piece of context the next agent needs to be productive
> within 5 minutes.

---

## TL;DR (read this first)

- **Branch:** `native-pyqt6` (active dev, push here)
- **HEAD:** `679034c` "fix(reports): save PDFs to Downloads folder"
- **Tests:** **406 collected** baseline (`py -m pytest tests/ -q`). Studio focused sweep is **94/94** green; the broader suite has the pre-existing modal-dialog flake noted in the prior handover (`test_preview_without_engine_does_not_crash` in `test_playlists_screen.py`).
- **App:** boots clean, all features confirmed working by operator end-to-end.
- **Operator:** Kavish Sharma, **FCP 90.8 MHz, Sikar, Rajasthan, India** (was KISS FM 91.5 in prior session — operator rebranded mid-session via Settings; codebase is now station-agnostic, see commit `1c665b6`).
- **Hardware target:** 1366×768 desktop monitor.
- **Major feature shipped this session:** complete sweeper ecosystem (Sweepers Library + Editor dialog + Studio overlay + Clock Editor specific-sweeper picker) + Play Report PDF generator + station name made flexible via `Settings.station_display`.

---

## Pre-flight protocol (mandatory — paste raw output)

```
git branch --show-current     # native-pyqt6
git status                    # only .claude/scheduled_tasks.lock (transient) + design_refs PNGs
git log --oneline -3          # 679034c top
py -m pytest tests/ -q        # 406 tests collected; Studio sweep 94/94 green
```

If anything mismatches → STOP and surface in plain Hindi. Don't paper over.

Studio focused sweep (use this for tighter feedback during Studio-area work):

```
py -m pytest tests/test_studio_*.py tests/test_sweeper*.py \
              tests/test_spot_play_report.py \
              tests/test_clock_editor_sweeper_config.py -q
```

---

## Project basics

- **Name:** RadioAI Studio Pro v2.0
- **Stack:** PyQt6 (pure native widgets — NO HTML/WebView/Flask/JS), BASS audio via `pybass3`, SQLite WAL.
- **Project root:** `E:\RadioAI_v2` (Git Bash sees as `/e/RadioAI_v2`)
- **Modeled on:** Jazler SOHO (broadcast operator's mental model)
- **Run:** `py main.py` (or `py main.py --debug` for verbose logging)
- **Python:** 3.14, Qt 6.11
- **Note:** `pytest` is NOT on PATH — always use `py -m pytest`

---

## GitHub repository

- **URL:** https://github.com/kundansharma903-code/radioai-studio-pro
- **Branches:**
  - `native-pyqt6` — active development, push here
  - `main` — base / PR target (rarely touched directly)
  - `responsive-pilot-studio` — preserved failure record from Phase 2 pilot. **DO NOT DELETE.** Used for forensic review when next responsive attempt is planned.
- **Push convention:** every feature/fix lands as a single focused commit on `native-pyqt6`. Multi-piece work uses sequential commits, one push at end.
- **All 19 session commits are local on `native-pyqt6`** — operator has not requested a push yet. Confirm before pushing.

---

## Database

- **Path:** `%LOCALAPPDATA%\RadioAI\radioai.db` → `C:\Users\hp\AppData\Local\RadioAI\radioai.db`
- **Schema:** `database/schema.sql` (idempotent `CREATE TABLE IF NOT EXISTS`)
- **Seeds:** `database/seeds.sql` (`INSERT OR IGNORE` only)
- **Manager class:** `core/database.py` — thread-safe singleton, all SQL lives here
- **Key tables:**
  - `songs` (396 rows in dev DB) — track library
  - `jingle_pads` — instant jingles for the 9-tile grid in Studio
  - `campaigns` + `spot_files` + `campaign_schedule` — ad spots
  - `clocks` + `clock_slots` — Jazler-style hour rotation patterns
  - `auto_schedule` — 24×7 grid binding (day, hour) → clock_id
  - `force_clocks` — one-off overrides
  - `broadcast_log` — air log (every play landed here, History panel + Play Report Actual mode read from it; `campaign_id` column is populated for spot entries — that's what drives Play Report Actual mode)
  - **`sweepers`** — extended this session via additive migration. Original columns: id, name, category, file_path, duration_ms, position, properties, playlister_code, is_enabled. **New columns** (commit `53f41e1`): auto_code, author, entry_date, comments, bpm, era_year, volume_song_pct, volume_sweeper_pct, offset_seconds, fade_seconds, clock_id, min_gap_minutes, max_per_hour. Migration helper: `db._ensure_sweepers_columns()` — idempotent, runs on dialog open.
- **Inspect quick:**
  ```bash
  py -c "from core.database import Database; db=Database(); print(list(db._conn().execute('SELECT COUNT(*) FROM broadcast_log').fetchone()))"
  ```
- **Operator's current state:** clock 1919 ("New test002") with 12 alternating song/sweeper slots, sweeper RR_SW (id=59) pinned via item_id, 24 cells in `auto_schedule` for Thursday. Boot log audit confirms the `auto_schedule` grid persistence on every restart (commit `3a57a54`).

---

## Figma reference

- **File key:** `7oN9K61g94wKx3nu44KKDF`
- **File name:** "RadioAI — Control Panel PREMIUM"
- **Pages:** "Page 1" (default, contains all major frames), "Studio Screens v3", "Scheduling Screens v2", "Ref Images Scheduling Tab"
- **Studio v3 main frame:** `312:2` (1920×1080 — Premium Jazler Style)
- **Frame mappings (full table in CLAUDE.md):**
  - Control Panel `5:2`, Songs Library `12:2`, Spots & Commercials `35:2`, Scheduling `50:2`, Main Auto Schedule `161:2`, Clock Editor `165:2`, AI Magic `170:2`, Spots AI Monitor `174:2`, Studio v3 `312:2`
- **Sweeper ecosystem frames added/used this session:**
  - `46:2` Sweepers Library (1440×900)
  - `108:2` Add New Sweeper Dialog (900×660)
- **Play Report frames CREATED this session via `use_figma` MCP:**
  - **`412:2`** Play Report Tab — Spots & Commercials right-panel content (560×680)
  - **`415:2`** Play Report PDF Output Preview — A4 portrait Jazler-style (595×842)
  - Both placed at x=47200 on Page 1, after the existing Studio v5 frame at x=44442
- **Figma MCP tools available:** `use_figma` (write), `get_design_context`, `get_screenshot`, `get_metadata`, `get_variable_defs`. The `use_figma` tool can create/edit frames programmatically — this session created the Play Report frames directly via JS Plugin API code. Reference screenshots saved to `design_refs/`:
  - `play_report_tab_412_2.png`
  - `play_report_pdf_415_2.png`
  - `sweepers_library_46_2.png`
  - `sweepers_add_dialog_108_2.png`

---

## Architecture map

| Layer | File | Notes |
|---|---|---|
| Constants | `core/constants.py` | `WINDOW_W=1920, WINDOW_H=1080`. `STATION` constant changed to generic "RadioAI Studio" fallback (commit `1c665b6`) — UI bypasses it via `Settings().station_display` |
| Settings | `core/settings.py` | Singleton cache. **New `station_display` property** (commit `1c665b6`) returns `f"{name} {frequency}"` (e.g. "FCP 90.8 MHz"). Used by every UI header banner + the Play Report PDF |
| Database | `core/database.py` | ~2400 lines, all SQL here. Sweeper migrations + `add_sweeper`/`update_sweeper`/`next_sweeper_auto_code` helpers added this session (commit `53f41e1`) |
| Audio Engine | `core/audio/engine.py` | **Phase A LOCKED** — multi-channel BASS + Qt signals. **New `get_levels(channel_id) -> (float, float)` helper** (commit `3a57a54`) feeds the Studio LR meter widget at 30Hz |
| BASS plumbing | `core/audio/_bass.py` | ctypes argtypes for BASS DLL. **`BASS_ChannelGetLevel`** declared this session for the level-meter wire |
| BASS lifecycle | `core/audio_engine.py` | Just `bass_init()` / `bass_free()` — class definition is legacy/orphaned but still imported, harmless |
| Scheduler | `core/scheduler/engine.py` | 1Hz tick on QThread, signal-driven dispatch. `peek_next(n)` (non-destructive) + `pick_next_item` (destructive). The cursor-eating bug was fixed in commit `bd16568` |
| Instant Jingles | `core/instant_jingle_engine.py` | Adapter over AudioEngine, 8-pad polyphony cap |
| **Sweeper Engine** | `core/sweeper_engine.py` | **Wired live this session** — was standalone, now MainWindow holds one shared instance and Studio routes overlay-style sweepers through it |
| **Reports** | `core/reports/spot_play_report.py` | **NEW this session** — QPdfWriter+QPainter PDF generator for Spot Play Reports. Uses `Settings.station_display` for branding, saves to `~/Downloads/RadioAI Reports/` |
| Style | `assets/style.qss`, `assets/premium.qss` | QSS — applied at app boot |
| Main window | `ui/main_window.py` | 1920×1080 shell + QStackedWidget. **SweepersLibrary mounted** + **SweeperEngine instantiated** this session |
| Entry point | `main.py` | Logging → BASS → DB → Settings → QApplication → MainWindow. **Auto-schedule persistence audit log added** (commit `3a57a54`) |
| **Studio screen** | `ui/studio.py` | **3900+ lines** — current working file. New this session: SweeperEngine wiring, sweeper overlay dispatch, Libraries panel sweeper tile, peek-vs-pick split for NEXT chip, auto-start on showEvent, skip-bad-files in auto-advance, StopNext skip-to-next, level meter 30Hz poll, second hand on analog clock |
| **Sweepers Library** | `ui/sweepers_library.py` | **NEW this session** (commit `58246f3`) — 1440×900 screen matching Figma 46:2 |
| **Sweeper Editor Dialog** | `ui/dialogs/sweeper_editor_dialog.py` | **NEW this session** (commit `53f41e1`) — Add/Edit dialog matching Figma 108:2 |
| Spots & Commercials | `ui/spots_commercials.py` | **Play Reports tab built out** this session (commit `f3824ae`) — replaces the previous stub with the form from Figma 412:2 |
| Clock Editor | `ui/clock_editor.py` | **Specific-sweeper picker added** (commit `fe285fe`) — when element_type='sweeper' is selected, the filter card swaps to show a sweeper picker + position dropdown |
| Studio legacy | `ui/studio_legacy.py` | Pre-v3 backup. **DO NOT TOUCH** until on-air verified. Rollback insurance |

---

## Commits this session (newest → oldest)

| Commit | Theme |
|---|---|
| `679034c` | fix(reports): save PDFs to Downloads folder + diagnostic logs in open path |
| `3822de5` | fix(spots): Play Report calendar popup styling + Edge "File not found" race |
| `d1a3e11` | fix(spots): Play Reports tab crash — undefined BG_DARK in radio stylesheet |
| `f3824ae` | **feat(spots): Play Reports — PDF generator + tab UI (Figma 412:2 + 415:2)** |
| `1c665b6` | **refactor(ui): station name + frequency now flow from Settings (no hardcoding)** |
| `366b654` | feat(studio): add second hand to the analog wall clock |
| `3a57a54` | feat(studio): live LR level meters + auto-schedule persistence audit log |
| `6c86ddf` | fix(studio): StopNext button is now skip-to-next, not stop-after-current |
| `522ddf5` | fix(studio): StopNext button shows armed state + toggles to disarm (later replaced by skip-to-next) |
| `ab0c1f1` | fix(studio): auto-advance skips items with missing file_path; idle UX on bad file |
| `1f6eccf` | feat(studio): auto-start scheduler on Studio showEvent when clock assigned |
| `bd16568` | **fix(studio): NEXT chip / RDS panel must NOT advance scheduler cursor** (audit-driven; was eating slot pairs) |
| `111c4ec` | fix(sweepers): scheduler-picked sweeper plays sequentially when deck is idle (RR_SW regression fix) |
| `fe285fe` | **feat(sweepers): Phase 3 — Clock Editor specific-sweeper picker + position** |
| `c76d804` | **feat(sweepers): Phase 2 — Studio Libraries panel sweeper tile + overlay** |
| `34f7cf9` | **feat(sweepers): Phase 1 — wire SweeperEngine into Studio overlay path** |
| `53f41e1` | **feat(sweepers): Add/Edit Sweeper Editor Dialog (Figma 108:2)** |
| `58246f3` | **feat(ui): Sweepers Library screen (Figma 46:2)** |
| `74b009e` | fix(spots): plain click toggles cells; drag adds rectangle additively |

---

## Operator-facing features — current state

### ✅ Working (operator confirmed)

| Feature | Status |
|---|---|
| Studio v3 visual layout | Pixel-aligned to Figma 312:2, 1920×1080 |
| Audio playback (Play / Stop / Pause) | Wired through AudioEngine. Stop is deck-only (jingles survive) |
| Instant Jingles (9 tiles + 1-5 hotkeys + Esc) | DB-bound, real audio dispatch, DEMO countdown |
| AUTO pill toggle | Starts/stops scheduler + flips `_auto_advance_enabled`, with immediate refresh. **Operator-stop latch** prevents auto-restart on subsequent showEvents |
| **Auto-start on Studio show** | When a clock is assigned to current (weekday, hour) cell + scheduler not running + operator hasn't latched off, scheduler starts on Studio screen entry |
| Up Coming queue | Scheduler-driven (`peek_next`) when AUTO ON, fallback when OFF. Excludes played + currently-playing |
| **NEXT chip / RDS panel** | **Now uses non-destructive peek** — no more cursor-eating bug |
| Active Clock indicator | Updates from 4 paths (1Hz tick, showEvent, AUTO toggle, scheduler signal) |
| History panel | Logs every play (manual + auto), refreshes on play-start, dedupes consecutive dupes in display. **Sweeper plays now logged correctly with `entry_type='sweeper'`** |
| Spot dispatch | Defers to song-end (no mid-song cut). NowPlayer reflects spot name during airing |
| Hour-boundary detection | Auto-loads new clock at hour rollover via scheduler tick |
| **Auto-advance skip-bad-files** | Items with missing/invalid `file_path` are skipped (up to 6 per dispatch) instead of stalling the broadcast |
| **StopNext button** | Skip-to-next semantic — click immediately stops current + auto-advances to next |
| **LR level meters** | 30Hz poll on `engine.get_levels(deck_cid)` → live bars |
| **Analog clock second hand** | Red, longest of three, ticks 1Hz (cosmetic) |
| **Sweepers Library** (Figma 46:2) | Full screen with table, filter, details panel. `+ Add New` opens editor dialog. Toast stubs: Mass Import / Edit Categories / Delete / Export to Playlister |
| **Sweeper Editor Dialog** (Figma 108:2) | Add/Edit modes, AUTO CODE pill (SWP-NNNN), category tile grid, position settings, audio file picker, availability/overlay/scheduling/separation panels |
| **Sweeper ecosystem wiring (Phases 1-3)** | Engine wired, scheduler-driven overlay (or sequential deck-load when deck idle / Independent position), manual play from Studio Libraries panel, Clock Editor specific-sweeper picker |
| **Spots Programming click-to-toggle** | Plain click toggles cells additively (was clear-and-add — operator was frustrated) |
| **Play Reports tab** (Figma 412:2 + 415:2) | Campaign info card, Actual/Scheduled mode toggle, date range pickers (with dark-styled calendar popup), Generate button. Saves PDF to `~/Downloads/RadioAI Reports/` and opens via `os.startfile` |
| **Station name + frequency are dynamic** | Operator changes Settings → every screen banner + Play Report PDF reflect new branding instantly. `Settings().station_display` is the single source of truth |

### 🟡 Partially working / known limitations

- **AUTO pill at x=1464** — may be off-screen on 1366×768 monitor (Kavish's hardware). Phase 2 responsive layout would solve this; pilot canceled. Workaround: launch maximized.
- **Older premium screens (Hub / Playlists / AutoSchedule / ClockEditor / PlaylistEdit)** — hardcoded `setFixedSize(1440, 900)`, top-left anchored in 1920×1080 main stack. On 1366×768 monitor → scrollbars appear. Phase 2 work pending.
- **Sweeper auto-dispatch timing** — currently fires immediately when scheduler returns the item (or falls through to deck-load if deck idle / Independent position). True "Bridge at End" overlay-during-song needs scheduler peek-ahead at song-START (not implemented). Sequential play is the correct fallback semantic.
- **Single-slot pending spot** — if 2 spots fire while a song plays, the most-recent overwrites the earlier. Flagged for future queue-based enhancement.
- **broadcast_log → Play Report Actual mode** — works only when `broadcast_log.campaign_id` is populated for spot entries. Existing pipeline already populates this for scheduler-dispatched spots; manual spot plays may not have campaign_id. Verify with `SELECT entry_type, campaign_id FROM broadcast_log WHERE entry_type='spot' LIMIT 10` if a customer report comes back empty.
- **Ad Company field on Play Report PDF** — currently blank (no schema field). Either pull from Settings (a new `report_ad_company` key) or add as a per-campaign field. Carry-over flagged in `f3824ae` commit message.

### 🔴 Not yet built

- **Phase 2 Part 2** — propagate responsive container to non-Studio screens (after fixing pilot's QShortcut/modal/perf issues)
- **Stitcher integration** — pre-mix "Coming Up Next" block into one WAV
- **AI Daily Scheduler integration** with Studio
- **RDS / Icecast streaming output** — wire SIGNAL pill to actual stream state
- **Sweeper Mass Import** — bulk-add sweepers from a folder (toast stub)
- **Sweeper Edit Categories** — manage category labels (toast stub)
- **Sweeper Delete** — destructive-confirm flow (toast stub; operator-confirm dialog needed)
- **Sweeper Export to Playlister** — write active sweepers to Playlister integration file (toast stub)
- **Sweeper preview audio in the Sweepers Library scrubber** — embedded scrubber is cosmetic right now; wiring to AudioEngine for preview channel is deferred
- **Mix Point dragging on the Sweeper Editor timeline strip** — visual only
- **Audio cue editor hookup for sweepers** — "Edit" button next to file picker is a toast stub
- **AI Auto-fill Metadata for sweepers** — stub button (no LLM hookup)
- **Frame 12 (294:2) — Final Log Creator Day Picker**
- **Frame 13 (297:2) — Build Log inner**
- **Standalone Instant Jingles screen IJE consolidation** — currently has own instance, not shared with Studio's
- **Push to GitHub remote** — 19 local commits on `native-pyqt6`, operator hasn't asked for push yet

---

## NIGHT_LOG carry-overs (forensic record)

Read `NIGHT_LOG.md` end-to-end before starting major new work. Key past incidents:

1. **2026-05-04 — DELETE-with-LIKE wipe** — `LIKE '__%'` matched all rows ≥2 chars long → nuked 15 campaigns + 791 schedule rows. CLAUDE.md "Destructive operation protocol" was added in response.
2. **"Saved clock vanished" display bug** — Available Clocks panel sliced 3 rows + ordered by name ASC → fresh clocks with lowercase names sorted to end + got hidden. Fixed via consumer-side `id DESC` sort.
3. **Pre-existing modal-dialog hung test** — `test_preview_without_engine_does_not_crash` in `test_playlists_screen.py` hangs on PyQt 6.11 + `-platform minimal`. Permanently deselected. Not caused by recent work.
4. **Studio v3 9-step rebuild** — disciplined per-step checkpoints to avoid structural drift.
5. **Phase 2 responsive pilot canceled** — branch `responsive-pilot-studio` preserved as failure record.
6. **(NEW this session) NEXT chip cursor-eat bug** — `_apply_idle_state` and `_apply_playing_state` were calling `_compute_next_song` (which uses destructive `pick_next_item`) for display-only refreshes. Every song-start ate an extra slot. Fixed in `bd16568` by adding `_peek_next_for_display` that uses non-destructive `peek_next`.
7. **(NEW this session) BG_DARK NameError crash** — Play Reports tab paint code referenced `BG_DARK` which isn't imported in spots_commercials.py. Tab open silently crashed the app via Qt's slot-bridge swallowing the traceback. Lesson: paint stylesheets are runtime-evaluated; an undefined token kills the GUI. Fixed in `d1a3e11` by switching to `BG_BASE`.
8. **(NEW this session) Edge "File not found" on freshly-written PDFs** — QPdfWriter held the file handle until Python GC; Edge's sandbox raced the AppData path. Fixed in `679034c` by saving to `~/Downloads/RadioAI Reports/` (Edge has unrestricted access there) + explicit `del writer` + `gc.collect()` before opening.

---

## Established conventions (discipline rules)

These were either inherited or reinforced this session. **Follow these without being told.**

### Communication style

- **Hindi-English mix** is fine and preferred for operator-facing summaries
- **Plain Hindi** required for verification questions to operator (broadcast-language, not coder-language)
- **Senior-dev pushback ON** — surface contradictions between prompt and source code before editing
- **Investigation-first** — read 3-4 files, post 4-line summary, wait for confirmation BEFORE editing
- **Trust-but-verify** — source code wins over docs/prompts
- **Brief responses** — narrate intent in 1-2 sentences before tool calls; long planning prose annoys operator
- **End-of-turn summary:** one or two sentences. What changed and what's next. Nothing else.

### Coding style

- **Cache QGradient/QColor/QFont in `__init__`** (performance invariant)
- **Partial repaints via `self.update(QRect)`** not bare `self.update()`
- **NO db calls in paintEvent**, NO `self.update()` inside paintEvent
- **NO `setMouseTracking`** unless cursor change needed
- **Drop shadows via `QGraphicsDropShadowEffect`** (one effect per widget — Qt limitation)
- **Engine signals throttled** — position ≤4Hz, level meters ≤30Hz
- **Try/except every scheduler `_on_tick` path** — broadcast safety, never freeze 1Hz heartbeat
- **`hasattr(scheduler, "signal_name")` defensive guards** when adding new scheduler signals — backward compat with `_FakeScheduler` mocks in existing tests
- **Settings is a singleton** — `from core.settings import Settings; Settings().station_display` works from any module after main.py boot. Don't pass it through ctors.
- **Inter font family is "Inter Variable"** (not "Inter") — that's the family name `InterVariable.ttf` registers. Mismatch produces glyph fallback (boxes in PDFs). Centralized in `ui/widgets/_tokens.py` as `INTER_FAMILY` and in `core/reports/spot_play_report.py` as the same constant.
- **PDF generators must `del writer` + `gc.collect()`** before returning — Windows / Edge race the file handle otherwise.
- **Use `os.startfile()` on Windows** for opening files in default handler — never races freshly-written files. Falls back to `QDesktopServices` elsewhere.

### Test discipline

- **Live-DB fixtures use unique prefix** (`_test_studio_<uuid8>`, `_test_active_clock_<uuid8>`, `_test_sweepers_<uuid8>`, etc.) + `try/finally` cleanup
- **Mock pattern:** `_FakeEngine` / `_FakeScheduler` / `_FakeIJE` / `_FakeSweeperEngine` per topic in test files. `_RecordingSignal` for pyqtSignal stand-in
- **Don't modify existing test files** — add to topical files or create new ones
- **Run focused tests after each piece** before full suite
- **Full suite must stay green** — zero regressions tolerance
- **Wall-clock-boundary flake** in `test_live_at_tick_refreshes_via_existing_1hz_timer` — pre-existing 1100ms wait race. Re-run usually passes.
- **(NEW this session) Test fakes that pass file_path strings need real on-disk paths** — `_compute_next_song` validates `os.path.exists(file_path)` to skip broken rows. Test fakes should use `sys.executable` or `tmp_path` files as stand-ins; otherwise the new validation skips them and tests fail. Fixed pattern visible in `tests/test_studio_sweeper_overlay.py` and `tests/test_studio_next_chip_no_cursor_advance.py`.

### Commit discipline

- **One focused commit per task** — heredoc commit message format
- **Commit message body:** problem + root cause + fix + test count delta. Include "Co-Authored-By: Claude Opus 4.7 (1M context)"
- **No `--no-verify` / `--amend`** — always create new commits, hooks must pass
- **Push to `native-pyqt6` only** unless on a deliberate feature branch
- **Don't `git add -A`** — explicitly add files

### Destructive ops protocol (CRITICAL — caused real incident on 2026-05-04)

- **Never use `LIKE` patterns** for cleanup queries (caused 15-campaign + 791-row wipe)
- **Always run `SELECT COUNT(*)` first** with the same WHERE clause, get explicit user confirmation
- **Wrap in `BEGIN TRANSACTION`** for multi-row cleanup
- **Use `db.delete_*()` methods** for tables without `ON DELETE CASCADE`

### Locked code paths (DO NOT MODIFY without explicit approval)

- `core/audio/*` — Phase A LOCKED (added `get_levels` is the one carve-out — confirmed safe with operator)
- `core/instant_jingle_engine.py` — read-only after Phase A wiring landed
- `ui/studio_legacy.py` — rollback insurance until on-air verified
- `ui/instant_jingles.py` (standalone screen) — has its own IJE instance per Option 2 topology
- Existing test files (add new ones instead)

---

## Quick start for next session

1. Run pre-flight (paste output)
2. Read this file end-to-end
3. Skim `CLAUDE.md` (project guide, Figma frames, destructive op protocol)
4. Skim the most recent ~5 entries of `NIGHT_LOG.md` (incident history) — current session work isn't logged in NIGHT_LOG yet (nice-to-have backfill, not blocking)
5. Check git log to confirm HEAD matches `679034c` and tests pass
6. Wait for operator's task instruction — do NOT proactively pick up pending items

When the operator gives a task:
- **If it touches Studio v3** → read the relevant section of `ui/studio.py` (3900+ lines, navigate by class name) before editing
- **If it touches scheduler** → read `core/scheduler/engine.py` and any existing test for that area
- **If it touches sweeper ecosystem** → read `ui/sweepers_library.py`, `ui/dialogs/sweeper_editor_dialog.py`, and `core/sweeper_engine.py`
- **If it touches Play Report** → read `core/reports/spot_play_report.py` and the `_build_tab_play_reports` method in `ui/spots_commercials.py`. Tests in `tests/test_spot_play_report.py` are the contract.
- **If it's a new screen / Frame 12 or 13** → fetch Figma context first, then plan before coding
- **Always investigation-first, 4-line summary, wait for confirmation, then implement**

### Likely next-session topics (operator-driven, but plan ahead)

The operator has flagged these as "later sessions" during this run; not a priority order, just memory aids:
- Push 19 local commits to GitHub remote (operator approval needed)
- Sweeper Mass Import dialog (current button shows toast)
- Sweeper Edit Categories dialog
- Sweeper Delete with destructive-confirm flow
- Sweeper preview audio in the Sweepers Library scrubber
- Audio cue editor hookup for sweepers (Edit button)
- Ad Company field on Play Report PDF — Settings key OR per-campaign field
- AI Auto-fill Metadata for sweepers (LLM hookup)
- Phase 2 responsive layout retry (`responsive-pilot-studio` branch is the failure record)

---

## Operator profile (broadcast operator)

- **Name:** Kavish Sharma
- **Station:** FCP 90.8 MHz, Sikar, Rajasthan, India (replacing Jazler SOHO)
- **Hardware:** 1366×768 desktop monitor (smaller than the 1920×1080 design canvas — Studio v3 fits, older premium screens letterbox + scrollbar)
- **Communication style:** Hindi-English code-switch is normal. Senior-dev pushback expected. Patient with disciplined work but pushes back on scope creep, over-engineering, and silent papering-over.
- **Workflow expectation:** investigation-first, 4-line summary, wait for confirmation BEFORE editing. Don't claim audio/visual outcomes you haven't verified — the test suite proves wire shape, not actual broadcast audio. On-air smoke is always operator-verified, not agent-claimed.
- **Verbal cues to remember:**
  - "go" / "ok" → proceed
  - "great" / "good" → confirmed, move on (often paired with commit instructions)
  - "commit this" → commit now
  - "run main.py" → launch app for visual smoke
  - "its not working" / similar → root-cause investigation, no quick patches
  - "do one thing" → small focused task incoming

---

## Last words

Operator (Kavish) is patient with disciplined work but pushes back on scope creep, over-engineering, and silent papering-over. Surface true blockers in plain Hindi. Don't claim audio/visual outcomes you haven't verified — the test suite proves wire shape, not actual broadcast audio. On-air smoke is always operator-verified, not agent-claimed.

The sweeper ecosystem is the headline feature this session — read the four `feat(sweepers)` commit messages end-to-end before touching anything in that area; the Phase 1/2/3 split is intentional and the boundaries matter.

Good luck.

— Previous session, signing off at HEAD `679034c`, 406 tests collected, app boots clean, operator confirmed Play Report end-to-end working.
