# RadioAI Studio Pro — PROJECT BIBLE (Complete Onboarding)

> **Purpose of this document.** This is the single, authoritative,
> read-once-and-understand-everything onboarding reference for a NEW
> Claude session (or new developer) joining the RadioAI Studio Pro
> project. Read this end-to-end and you will have the full mental
> model needed to fix bugs and extend the software.
>
> This is DIFFERENT from the daily `HANDOVER_*.md` files. Those are
> session diaries ("what changed today, what to do next"). THIS file
> is the timeless architectural bible ("what the software IS, how it
> works, where everything lives").
>
> **Read order for a cold start:**
>   1. THIS file (PROJECT_BIBLE.md) — complete architecture
>   2. `HANDOVER_2026_07_09.md` — **the latest session state**
>      (2026-07-03 → 07-09: Break Policy, aircheck, watchdog, backup/
>      restore, the ONE open task A+B, current live state, lessons).
>      Then `HANDOVER_2026_05_17.md` for the 3 critical invariants +
>      older feature history.
>   3. `CLAUDE.md` — the short project guide (note: its Figma table
>      is STALE; use the table in this bible instead)
>   4. Older `HANDOVER_*.md` files only if you need historical
>      context on a specific feature
>
> **Last verified against codebase:** 2026-07-01 (HEAD `cac4adc`).

---

## PART 1 — WHAT THIS PROJECT IS

### 1.1 One-paragraph summary

RadioAI Studio Pro is a **professional Windows desktop radio
automation software** — the software that runs a radio station's
on-air playout. It decides what plays next (songs, ads, jingles,
sweepers, voice drops), plays it through the sound card, logs what
aired, and lets a human operator take manual control at any moment.
It is modeled on **Jazler SOHO** (the industry-standard automation
suite) but adds AI-native scheduling. Built for **KISS FM 91.5 /
FCP Radio, Jaipur, India**, published under **MonoLoop Productions**.

### 1.2 The operator (very important — this drives everything)

- **Name:** Kavish Sharma
- **Location:** Sikar / Jaipur, Rajasthan, India
- **Publisher brand:** MonoLoop Productions
- **Station:** KISS FM 91.5 / FCP Radio (station name is
  configurable via Settings → `Settings.station_display`)
- **Hardware:** 1366×768 desktop monitor (design canvas is larger;
  screens letterbox / scroll)
- **Communication style:** Hindi-English code-switch is normal and
  expected. Plain Hindi for verification questions. Senior-dev
  pushback is WELCOME — surface contradictions before editing.
  Investigation-first workflow: read files, post a 4-line summary,
  wait for confirmation BEFORE editing.
- **Verbal cues:**
  - "go" / "ok" / "process" / "confirm" → proceed
  - "great" / "perfect" / "wonderful" → confirmed, move on
  - "commit this" / "commit all" → commit now
  - "run main.py" → launch app for visual smoke test
  - "its not working" → root-cause investigation, no quick patches
  - "kar do" / "bana do" / "fix this" → just do it, operator decided
  - "isko rehne do" / "let it be" / "baad mein dekhenge" → defer this
  - "did you understand?" → confirm understanding + ask clarifying
    questions BEFORE coding

### 1.3 How to run

```
cd E:\RadioAI_v2
py main.py                 # launch the app
py main.py --debug         # verbose logging
py main.py --maximized     # test on full 1920×1080
```

Python 3.14, Qt 6.11, Windows x64. Note: `pytest` is NOT on PATH —
always use `py -m pytest`.

**Built / distributed forms:**
- Standalone exe: `dist\RadioAI Studio Pro\RadioAI Studio Pro.exe`
- Installer: `installer\RadioAI_Studio_Pro_Setup_v2.0.0.exe`
- Rebuild exe: `py -m PyInstaller RadioAIStudioPro.spec --clean --noconfirm`
- Rebuild installer: `"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" RadioAI_Setup.iss`

---

## PART 2 — TECH STACK & THE "STALE DOCS" WARNING

### 2.1 Actual tech stack (verified in code)

| Layer | Technology |
|---|---|
| UI | **PyQt6, pure native widgets** — NO HTML, WebView, Flask, or JavaScript ANYWHERE |
| Audio | **BASS** (un4seen) via **`pybass3`** ctypes wrapper — NOT python-vlc |
| Audio addon | **BASSmix** (`bassmix.dll`) — present but DORMANT (see invariants) |
| Pre-mix | **pydub** (Stitcher engine mixes WAV blocks) |
| Database | **SQLite** with WAL journaling, thread-safe singleton |
| AI (rotation) | Local algorithm (Time-Slot Freshness) — no external API for rotation |
| AI (SOTG transcription) | Google Gemini / OpenAI adapters |
| Packaging | PyInstaller (onefolder) + Inno Setup 6 |

### 2.2 ⚠ STALE DOCUMENTATION WARNING — read this or waste hours

Several docs in the repo describe an OLDER architecture that no
longer matches the code. **Trust the code, not these docs:**

| Stale claim (in blueprint.md / CLAUDE.md) | Actual reality |
|---|---|
| "Audio via python-vlc" | It's **BASS via pybass3**. No VLC anywhere. |
| "`core/audio_engine.py` is the playback engine" | That file ONLY holds module-level `bass_init()` / `bass_free()`. The real engine class is **`core/audio/engine.py`** (`AudioEngine`). |
| "`core/scheduler.py`" | Does NOT exist. The real scheduler is **`core/scheduler/engine.py`** (`SchedulerEngine`). |
| "`core/auto_scheduler.py`, `core/ai_daily_scheduler.py`" | These are legacy/superseded. The live scheduling path is `core/scheduler/engine.py` + `core/rotation_ai_engine.py`. |
| "DB at `%LOCALAPPDATA%\RadioAI\radioai.db`" | Moved (Phase L) to **`%LOCALAPPDATA%\RadioAI Studio Pro\Database\radioai.db`**. |
| CLAUDE.md Figma table (nodes 5:2, 12:2, etc.) | STALE. Use the cumulative Figma table in PART 8 of this bible. |
| "33 tables, 395 songs" | Now **41 tables**; ~394 songs in dev DB. |

**Rule of thumb:** when a doc and the code disagree, the code wins.
When two docs disagree, the newest `HANDOVER_*.md` wins.

---

## PART 3 — THE THREE CRITICAL INVARIANTS (never break these)

These are locked. Breaking any one re-introduces a bug we already
fought. Code comments mark each with a banner. Do NOT touch without
explicit operator approval.

### Invariant #1 — `route_via_mixer = False`

**Where:** `ui/main_window.py` (AudioEngine instantiation) + the
default in `core/audio/engine.py` `AudioEngine.__init__`.

**What:** The Phase 5 BASSmix mixer migration (attempted 2026-05-17)
surfaced audible stutter + broken pause that could not be resolved
in-session. The entire BASSmix subsystem (`core/audio/_bassmix.py`,
`core/audio/mixer_bus.py`, `core/audio/vendor/bassmix.dll`) stays in
the tree but is FULLY DORMANT while this flag is False.

**Do NOT** flip to True without: (a) running
`scripts/diag_mixer_stutter.py` and hearing clean playback in
Variant 2, (b) diagnosing the root cause that defeated the earlier
attempt (HANDOVER_2026_05_17.md incident #26), (c) operator's
explicit greenlight.

### Invariant #2 — `_has_pending_dispatch()` gate

**Where:** `ui/studio.py`, checked at 3 fade-trigger callsites:
`_on_engine_mix_point_reached`, `_maybe_trigger_fade_out`,
`_dispatch_crossfade_overlap`.

**What:** When a SOTG or paid Spot is queued to fire after the
current song, all early-fade triggers MUST defer — the song plays
to its natural EOS, then the spot/SOTG fires immediately on a
truly-silent deck. If any callsite stops checking this gate, music
starts fading early while the spot plays over it → the "spot overlay
on music" complaint returns (HANDOVER_2026_05_17.md incident #25).

Music-to-MUSIC crossfades (no pending dispatch) still use the long
overlap — that is the operator's musical-segue feature. Only
music-to-NON-music defers.

### Invariant #3 — `_suppress_queue_emit` flag

**Where:** `core/scheduler/engine.py`, set/restored in `peek_next`'s
try/finally, checked in `pick_next_item` before `queue_changed.emit()`.

**What:** `peek_next(5)` calls `pick_next_item` 5 times to simulate
the upcoming queue (cursor restored after). Without the gate, each
of those 5 simulated calls emits `queue_changed` → Studio's handler
re-calls `peek_next` → 5 more emits → exponential cascade → UI
freezes ("NEXT chip frozen"). Any NEW method that walks the dispatch
loop non-destructively MUST also set this flag True during
simulation.

---

## PART 4 — REPOSITORY MAP

```
E:\RadioAI_v2\
├── main.py                       Entry point: logging → bass_init → DB → Settings → QApplication → MainWindow → bass_free
├── CLAUDE.md                     Short project guide (Figma table STALE)
├── PROJECT_BIBLE.md              THIS FILE
├── blueprint.md                  Extended spec (parts STALE — see PART 2)
├── HANDOVER_2026_05_*.md         Session diaries (17 is latest)
├── NIGHT_LOG.md                  Cumulative incident log (forensic)
├── LICENSE.txt                   MonoLoop Productions EULA (495 lines)
├── RadioAIStudioPro.spec         PyInstaller build recipe
├── RadioAI_Setup.iss             Inno Setup installer recipe
│
├── core/                         BUSINESS LOGIC (34 py files)
│   ├── database.py               Thread-safe SQLite singleton, ALL sql (~3,400+ lines)
│   ├── settings.py               Settings table cache (singleton)
│   ├── constants.py              Colors, paths (delegates to paths.py)
│   ├── paths.py                  Single source of truth for runtime paths + DB migration/bootstrap
│   ├── dialogs.py                Premium modal dialog primitives (confirm/info/warning/error)
│   ├── audio/                    THE AUDIO ENGINE (BASS)
│   │   ├── engine.py             AudioEngine — multi-channel BASS player (THE real one, 49KB)
│   │   ├── channels.py           Channel dataclass (per-channel state)
│   │   ├── _bass.py              BASS DLL constants + ctypes bindings
│   │   ├── _bassmix.py           BASSmix bindings (DORMANT — Phase 5)
│   │   ├── mixer_bus.py          MixerBus singleton (DORMANT — Phase 5)
│   │   ├── tags.py               ID3/metadata reading (mutagen)
│   │   ├── exceptions.py         AudioEngineError, ChannelError, FormatError
│   │   └── vendor/               bassmix.dll (x64) + README
│   ├── audio_engine.py           LEGACY: only bass_init()/bass_free() module funcs (main.py uses these)
│   ├── scheduler/                THE SCHEDULER
│   │   ├── engine.py             SchedulerEngine — 1Hz tick, clock walker, dispatch (57KB, THE real one)
│   │   └── events.py             EventType, ScheduledEvent dataclasses
│   ├── rotation_ai_engine.py     RotationAIEngine — Time-Slot Freshness hourly rotation
│   ├── stitcher_engine.py        StitcherEngine — pydub pre-mix "Coming Up Next"
│   ├── sweeper_engine.py         SweeperEngine — overlay player (1 sweeper at a time)
│   ├── instant_jingle_engine.py  InstantJingleEngine — 8-pad polyphony for live pads
│   ├── sotg_transcription_engine.py  SOTGTranscriptionEngine — drop → Gemini/OpenAI → summary
│   ├── reports/                  PDF generators (sotg_daily_report, spot_play_report)
│   └── transcription/            Gemini + OpenAI adapters (base + 2 impls)
│
├── ui/                           PYQT6 PRESENTATION (70 py files)
│   ├── main_window.py            App shell + QStackedWidget router + engine owner (1,494 lines)
│   ├── studio.py                 THE broadcast workstation (8,088 lines — biggest file)
│   ├── control_panel.py          Home hub (6 library cards + top nav)
│   ├── studio_legacy.py          Old Studio v2 (rollback insurance — DO NOT edit)
│   ├── <30+ screen files>        Libraries, scheduling, SOTG, settings, reports (see PART 7)
│   ├── dialogs/                  ~15 modal dialogs (base_dialog + specifics)
│   └── widgets/                  Shared design system (tokens, chrome, cards, tables)
│
├── database/
│   ├── schema.sql                41 tables, idempotent CREATE TABLE IF NOT EXISTS (702 lines)
│   └── seeds.sql                 14 categories + 51 settings, INSERT OR IGNORE (141 lines)
│
├── tests/                        80 files, ~860 tests collected
│   ├── conftest.py               Shared fixtures (qapp headless, bass lifecycle, song pickers)
│   └── test_*.py
│
├── scripts/
│   └── diag_mixer_stutter.py     5-variant BASSmix isolation diagnostic (for Phase 5 retry)
│
├── assets/                       icon.ico, splash.png, logo.png, style.qss
├── design_refs/                  Figma screenshot PNGs (untracked reference)
├── dist/  build/  installer/     Build outputs (git-ignored)
```

---

## PART 5 — THE ENGINES (business logic layer)

The MainWindow owns and wires **7 engines**. They all share the ONE
BASS output device (`bass_init` called once in main.py).

### 5.1 AudioEngine — `core/audio/engine.py`

The multi-channel BASS player. Everything audible goes through it.

- **Type:** `QObject`, multi-channel (up to `MAX_CHANNELS = 8`)
- **Channel model:** `load_file(path)` returns a never-reused
  integer channel id. Subsequent play/pause/resume/stop/cleanup
  reference that id. Per-channel state in a `Channel` dataclass.
- **Key methods:** `load_file`, `play`, `pause`, `resume`, `stop`,
  `cleanup`, `cleanup_all`, `set_volume`, `fade_volume_to`,
  `seek_to_ms`, `get_position_ms`, `get_duration_ms`, `get_levels`
  (for VU meters), `probe_duration_ms`.
- **Phase 1 sample-accurate syncs (added 2026-05-17):**
  `set_position_sync(cid, ms)` registers a `BASS_SYNC_POS` callback
  → emits `mix_point_reached(cid)` at the exact sample. `set_slide_end_sync`
  → emits `fade_completed(cid)`. These replaced 250ms polling for
  the fade trigger.
- **Signals:** `position_changed(cid, ms)`, `playback_ended(cid)`,
  `error_occurred(cid, msg)`, `channel_state_changed(cid, state)`,
  `mix_point_reached(cid)`, `fade_completed(cid)`.
- **Threading:** BASS sync callbacks fire from BASS's internal C
  thread. They emit a PRIVATE signal that Qt queues to the main
  thread. **NEVER call Qt or DB from inside a BASS callback.**
- **Phase 5 mixer (DORMANT):** `AudioEngine(route_via_mixer=False)`.
  When True (never, currently), streams are decode-only and routed
  through `MixerBus`. See Invariant #1.

### 5.2 SchedulerEngine — `core/scheduler/engine.py`

The broadcast brain. Decides what airs next.

- **Type:** `QObject` on its own `QThread`, 1Hz tick.
- **Clock walker:** resolves the active clock for the current
  (weekday, hour) via `force_clocks` override → `auto_schedule`
  grid fallback. Walks the clock's ordered slots from a cursor,
  dispatches by `slot_type` to a per-type picker.
- **Key methods:**
  - `pick_next_item(now)` — advances cursor, returns next item dict
    `{item_type, item_id, file_path, title, artist, duration_ms,
    clock_id, slot_idx}`. Item types: song / jingle / sweeper /
    station_id / voice_track / break(spot).
  - `peek_next(n)` — NON-DESTRUCTIVE lookahead. Snapshots cursor +
    state, calls `pick_next_item` n times, restores. **Sets
    `_suppress_queue_emit` (Invariant #3).** WARNING: random
    pickers re-`random.choice` on each call, so repeated peeks can
    return different songs — the CURSOR is deterministic, the song
    identity is not.
  - Per-type pickers: `_pick_song`, `_pick_jingle`, `_pick_sweeper`
    (filters unplayable file_path — see below), `_pick_station_id`,
    `_pick_voice_track`, `_pick_break`.
- **Signals:** `spot_due(campaign_id)`, `song_auto_advance()`,
  `break_approaching(sec)`, `next_break_in(sec)`,
  `schedule_reloaded()`, `active_clock_changed(clock_id, name)`,
  `queue_changed()` (the canonical UI-refresh signal),
  `started()`, `stopped()`, `error_occurred(msg)`.
- **Rotation consult:** `_pick_song` optionally consults the
  RotationAIEngine before its own selection ladder (Phase E5).
- **`_pick_sweeper` hardening (2026-05-17):** filters out sweepers
  with missing/empty `file_path` (operator's DB has 3 broken
  sweepers). Prevents the "studio stops playing" cascade.

### 5.3 RotationAIEngine — `core/rotation_ai_engine.py`

The "Time-Slot Freshness" rotation AI (operator's brainchild).

- **Type:** `QObject` + `QThread` + 1-hour `QTimer`.
- **Algorithm (operator-locked):** for each candidate song at hour
  H of a clock with primary category C, compute a weight:
  - `slot_age_days` = days since this song last played in hour H
    (weekday-agnostic)
  - base weight lookup: today→0.00 (hard veto), yesterday→0.05,
    2d→0.30, 3d→0.60, 4d→0.90, 5-6d→1.00, 7+→1.00, never→1.30
  - `primary_boost` ×1.2 if song's category == C, else ×1.0
  - vetoes: <4hr same-song, <1hr same-artist
  - pick = `random.choices(eligible, weights)`
- **Sister groups:** 2-5 categories pooled so their songs are
  eligible for each other's clocks (variety). Symmetric.
- **Plan lifecycle:** computes a daily plan (`ai_rotation_plans`
  envelope + `ai_rotation_decisions` rows). Statuses: pending /
  approved / discarded / auto_applied. Operator approves via the
  Daily Plan Review screen; 5-PM QTimer auto-applies if undecided.
- **Settings keys:** `rotation_ai_engine_enabled`,
  `rotation_ai_last_tick_at`, `rotation_ai_last_error`,
  `rotation_ai_last_plan_date`.

### 5.4 StitcherEngine — `core/stitcher_engine.py`

Pre-mixes a "Coming Up Next" hook montage into one WAV (via pydub)
before playback, so the deck plays a single seamless block. Config
in the single-row `stitcher_config` table. Triggered before breaks /
every N songs / top-of-hour.

### 5.5 SweeperEngine — `core/sweeper_engine.py`

Overlay player — a sweeper (dry voice-over) plays ON TOP of the
current song (separate BASS channel), it doesn't replace it.
Position options: Start of Song / Before Intro / Before End /
Bridge at End / Custom / Independent.

### 5.6 InstantJingleEngine — `core/instant_jingle_engine.py`

8-pad polyphony for the live jingle pads (1-9 hotkeys in Studio).
Manual, operator-triggered. Pads stored in `jingle_pads` /
`jingle_pallets`.

### 5.7 SOTGTranscriptionEngine — `core/sotg_transcription_engine.py`

For "Spot on the Go" (SOTG) drops: after a drop fires, sends the
audio to Gemini or OpenAI (adapters in `core/transcription/`) and
stores a 4-line summary in `sotg_assignments.ai_summary`.

---

## PART 6 — THE BROADCAST DISPATCH FLOW (how audio actually plays)

This is the heart of the software. Understand this and you
understand the app.

### 6.1 Normal song → song

1. Scheduler tick or Studio EOS calls `_compute_next_song(after_id)`.
2. That calls `scheduler.pick_next_item(now)` — walks the clock,
   returns a song dict. (Bad file_path? It skips, within a bounded
   budget, then falls back to the static `_queue_songs` list.)
3. `_on_queue_song_play(song)` loads it via `engine.load_file`,
   plays it, sets `_playback_cid` + `_playback_kind = "deck"`,
   registers a mix-point sync via `_register_mix_point_sync`.
4. As the song plays, `engine.position_changed` drives the waveform
   + progress bar. At the mix point (per-song `mix_point_ms`, or
   the global `fade_out_start` fallback), `mix_point_reached` fires.
5. `_on_engine_mix_point_reached` → **IF no pending spot/SOTG**
   (Invariant #2) → fade the outgoing song + start the next on a
   fresh channel (crossfade). The old channel's EOS cleans it up
   silently (`_fading_cid`).
6. At natural EOS, `_on_engine_playback_ended` runs the EOS paths.

### 6.2 The EOS paths (`_on_engine_playback_ended`)

In order:
- **(crossfade tail)** — outgoing faded channel finished → silent cleanup.
- **(a) spot resume** — a paid spot just ended → chain: pending SOTG
  > pending spot > resume song queue (from `_pre_spot_song_id` anchor).
- **(a') SOTG resume** — a SOTG drop ended → same chain priority.
- **(b) stop-next** — operator pressed Stop Next → drain ALL pending
  dispatches, go idle.
- **(c) loop** — loop enabled → replay same song, drain pending.
- **(d) auto-advance** — the normal path. Drain pending in priority
  order **SOTG > Spot > Song**, else `_compute_next_song` → play next.

### 6.3 Spots & SOTG (the FIFO + priority model)

- Spots come from the scheduler's `spot_due(campaign_id)` signal.
  SOTG drops come from the 5s `_sotg_check_tick`.
- Both use **FIFO lists**: `_pending_spots: list[int]` +
  `_pending_sotgs: list[dict]`. They APPEND (never overwrite) — so
  5 spots at the same minute all queue and fire back-to-back.
- **Priority order (operator-locked): SOTG > Spot > Song.**
- When pending exists, the current song plays to natural EOS with NO
  early fade (Invariant #2), then the spot/SOTG fires on a silent
  deck. Clean, no overlap.
- Up Coming panel prepends pending items + a T-60s preview (items
  scheduled within the next 60s) above the song queue, so the
  operator SEES what's about to fire.
- Stop-next / Loop / AUTO-off → `_drain_pending_dispatches` clears
  both lists.

### 6.4 UI refresh (the queue_changed contract)

- `scheduler.queue_changed` fires on real changes (cursor advance,
  schedule reload, clock change).
- Studio's `_on_scheduler_queue_changed` rebuilds the Up Coming
  panel via `_load_upcoming_queue` (which calls `peek_next`).
- The 1Hz Studio tick does NOT rebuild — it only re-renders the
  CACHED preview (fresh timestamps). Rebuilding at 1Hz would
  re-`random.choice` and shuffle the visible songs every second
  (the "queue changes automatically" bug — fixed 2026-05-17).
- `_check_upcoming_dispatches` returns a bool (did the T-60s preview
  lists change?) so the tick only does a full rebuild when something
  real changed.

---

## PART 7 — THE UI LAYER

### 7.1 MainWindow — `ui/main_window.py`

- A `QMainWindow` → `QScrollArea` → `QStackedWidget` router.
- Design canvas is 1440×900 for most screens, 1920×1080 for Studio
  and Final Log. On a smaller physical monitor, the QScrollArea
  scrolls / letterboxes.
- **Owns all 7 engines** (see PART 5). Instantiated in `__init__`.
- **Lazy screen mounting:** each screen is created once and reused.
- **Routing patterns:**
  - `_on_card_clicked(screen)` — Control Panel library cards
  - `_on_hub_screen_requested(key)` — universal router; parses
    parameterized keys like `clock_edit:42`, `playlist_edit:7`
  - `_on_nav_clicked(label)` — top-nav tabs (literal labels incl.
    "AI Magic ✦" with the sparkle)
  - `_on_breadcrumb(where)` — breadcrumb "back to home"
  - F9 hotkey → jump to Studio
- **Cleanup order (critical):** `_cleanup_engine()` stops scheduler
  FIRST (so no more signals fire into a tearing-down audio engine),
  then audio `cleanup_all`, then (dormant) MixerBus cleanup, then
  main.py runs `bass_free`.
- **Timers:** SOTG 23:59 auto-save (60s), rotation 5-PM auto-apply
  (60s), startup auto-mode trigger (150ms one-shot).

### 7.2 Studio — `ui/studio.py` (8,088 lines, THE big one)

The broadcast operator's control center. Figma 312:2 (v3 rebuild).
1920×1080. Zones (top to bottom):

- **Header (72h):** logo, wordmark, live clock, station card,
  SIGNAL/STREAM/AUTO status pills, Control Panel button, settings.
- **Master strip (96h):** `_NowPlayer` (live waveform + progress),
  `_NextChip`, `_ControlCluster` (transport buttons), `_LevelMeters`
  (VU), `_AnalogClock`, wordmark.
- **Body (820h):**
  - LEFT `_LibrariesPanel` (400w): type tiles (Songs/Spots/Sweepers/
    Jingles), action stack (Add/Insert/Replace/Delete/Prepair),
    songs table, category filter.
  - RIGHT: `_UpComingQueue` (scrolling cards), `_InstantJinglesPanel`
    (3×3 pads + hotkeys), `_HistoryPanel` (12 rows), `_NextBreakPanel`,
    `_RDSPanel`, `_ProblemsPanel`.
- **Bottom transport (80h):** `_BottomTransport` — play/pause,
  seek slider, AutoPlay toggle, Loop/Stop/Restart/StopAll.

**Key method groups** (grep by name):
- Playback: `_on_play_clicked`, `_on_pause_clicked`, `_on_deck_stop`,
  `_on_restart_clicked`, `_on_stop_next_clicked`, `_on_loop_toggled`.
- Queue: `_on_queue_song_play`, `_compute_next_song`,
  `_on_engine_playback_ended` (the EOS paths), `_load_upcoming_queue`,
  `_refresh_upcoming_panel`.
- Engine handlers: `_on_engine_position`, `_on_engine_mix_point_reached`,
  `_on_engine_fade_completed`, `_on_engine_error`.
- Scheduler handlers: `_on_scheduler_spot_due`, `_do_scheduler_spot_due`,
  `_on_scheduler_queue_changed`, `_on_active_clock_changed`.
- SOTG: `_sotg_check_tick`, `_do_sotg_fire`, `_play_sotg_file`.
- Sweepers: `_dispatch_overlay_sweeper`.
- Fade / dispatch: `_dispatch_crossfade_overlap`, `_maybe_trigger_fade_out`,
  `_register_mix_point_sync`, `_has_pending_dispatch`,
  `_drain_pending_dispatches`, `_pending_spot_to_card`,
  `_pending_sotg_to_card`, `_check_upcoming_dispatches`.
- Jingles: `_wire_instant_jingles`, `_on_jingle_hotkey_clicked`,
  `_play_jingle_at_index`.
- State: `_apply_idle_state`, `_apply_playing_state`, `_refresh_history`,
  `_update_status_pills`.

**Key state attrs:** `_playback_cid`, `_playback_kind` ("deck"/"spot"/
"sotg"/"sweeper"/"jingle"/"stitcher"), `_current_track`, `_queue_songs`,
`_pending_spots`, `_pending_sotgs`, `_pre_spot_song_id`,
`_pre_sotg_song_id`, `_fading_cid`, `_loop_enabled`,
`_stop_after_current`, `_auto_advance_enabled`.

### 7.3 Screens (cumulative — the CURRENT Figma table)

Figma file key: **`7oN9K61g94wKx3nu44KKDF`**. URL pattern:
`https://www.figma.com/design/7oN9K61g94wKx3nu44KKDF?node-id=<NN-NN>`
(hyphen form). Screenshots cached in `design_refs/*.png`.

| Screen (route key) | File | Figma | Purpose |
|---|---|---|---|
| control_panel | control_panel.py | 192:2 / 5:2 | Home hub: 6 library cards + top nav |
| songs | songs_library.py | 205:2 / 12:2 | Master songs catalog + categories + cue editor |
| instant_jingles | instant_jingles.py | 44:688 | 9-pad live jingle tool + pallet mgmt |
| spots | spots_commercials.py | 35:2 | Active campaigns + break scheduling |
| sweepers | sweepers_library.py | 46:2 | Sweeper overlays library |
| jingles | jingles_library.py | 44:2 | Station jingles catalog |
| stitcher | stitcher.py | 46:481 | "Coming Up Next" pre-mixer |
| studio | studio.py | **312:2** | Broadcast workstation (1920×1080) |
| final_log | final_log.py | 14:2 | Broadcast history viewer (1920×1080) |
| scheduling_hub | scheduling_hub.py | 231:3 | Premium hub: clocks/playlists/auto |
| playlists | playlists.py | 239:2 | Playlist manager |
| playlist_new | playlist_new.py | 243:2 | Create playlist |
| playlist_edit:<id> | playlist_edit.py | 248:2 | Edit playlist |
| main_auto_schedule | auto_schedule.py | 278:2 | 24×7 clock assignment grid |
| clock_new / clock_edit:<id> / clock_duplicate:<id> | clock_editor.py | 285:2 | Clock CRUD (slots, rules, hours) |
| settings_hub | settings_hub.py | 426:3 | Settings root |
| settings_general | settings_general.py | 68:2 | Station name, startup |
| settings_soundcard | settings_soundcard.py | 68:394 | BASS device + channels |
| settings_studio | settings_studio.py | 69:2 | Crossfade, fade curve, cue, VU |
| play_history | play_history.py | 437:3 | Per-song play analytics |
| category_performance | category_performance.py | 448:3 | Per-category report |
| rotation_health | rotation_health.py | 521:2 | AI rotation audit |
| ai_magic | ai_magic_hub.py | 454:3 | AI Magic landing (SOTG / Scheduling AI) |
| spot_on_the_go | spot_on_the_go_shell.py | 462:3 | SOTG 4-card hub |
| create_schedule | sotg_create_schedule.py | 469:3 | SOTG: create recurring shows |
| assign | sotg_assign.py | 474:3 | SOTG: per-day file + time |
| generate_report | sotg_generate_report.py | 497:2 | SOTG: daily PDF report |
| assign_api_key | sotg_assign_api_key.py | 503:3 | SOTG: Gemini/OpenAI keys |
| scheduling_automation | scheduling_automation_hub.py | 511:3 | Rotation AI hub + controls |
| review_daily_plan | scheduling_daily_plan_review.py | 512:2 | Rotation plan approval gate |

**Building a new screen:** always fetch Figma first
(`get_design_context` + `get_screenshot`), or design via `use_figma`
MCP if no frame exists. Build pure PyQt6, pixel-align to screenshot.
Then mount + route in MainWindow, add to `_refresh_station_branding`
qlabel_screens tuple, and wire the breadcrumb.

### 7.4 Dialogs — `ui/dialogs/`

All inherit `base_dialog.py` (frameless, draggable header,
scrollable content, pinned footer). Prefer the **premium dialog
primitives** in `core/dialogs.py` (`confirm/info/warning/error`) for
confirmations — they centre on the parent's top-level window in
SCREEN coords (bug fixed in commit `dc3397b`). Notable dialogs:
add_new_song, mass_import, jingle_editor, sweeper_editor,
audio_cue_editor, add_campaign, spot_programming, sister_group_picker,
edit_categories.

### 7.5 Shared widgets — `ui/widgets/`

- `tokens.py` (premium) + `_tokens.py` (legacy) — colors + fonts.
  New screens use `tokens.py`.
- `app_chrome.py` — shared Header + LiveTimePill for premium screens.
- Cards, tables, badges, clock faces, waveform widget, icons.

---

## PART 8 — THE DATABASE (41 tables by domain)

- **Location:** `%LOCALAPPDATA%\RadioAI Studio Pro\Database\radioai.db`
- **Schema:** `database/schema.sql` (idempotent). Seeds:
  `database/seeds.sql`.
- **Access:** ALWAYS through `core/database.py` (`Database`
  singleton). It has a `db.execute(sql, params)` compat method
  (SELECT/PRAGMA/WITH → rows; INSERT/UPDATE/DELETE → commits) plus
  hundreds of domain methods (`get_all_clocks`, `create_clock`,
  `delete_clock`, `get_spot_files`, `get_sotg_assignments_for_date`,
  etc.).

### Domains (grouped):

1. **Songs/music:** `categories`, `songs` (per-song cue points as
   both `*_ms` and `*_time`), `sister_groups`, `sister_group_members`.
2. **Spots/commercials:** `campaigns`, `spot_files` (CASCADE),
   `break_schedule`, `campaign_schedule`, `spot_schedules`.
3. **Jingles/sweepers/voice:** `jingles`, `jingle_pallets`,
   `jingle_pads` (CASCADE), `sweepers`, `voice_tracks`.
4. **Clocks/scheduling:** `clocks`, `clock_slots` (CASCADE),
   `auto_schedule` (CASCADE, 24×7 grid), `force_clocks` (CASCADE),
   `scheduling_rules`.
5. **Playlists:** `playlists`, `playlist_songs` (CASCADE).
6. **Final log:** `final_logs`, `final_log_entries` (CASCADE).
7. **Broadcast history:** `broadcast_log` (what actually aired;
   heavily indexed; drives play history + rotation enforcement).
8. **AI scheduling/rotation:** `ai_daily_log`, `ai_schedule_status`,
   `ai_schedule_warnings`, `ai_run_steps`, `ai_decisions`,
   `ai_insights`, `ai_rotation_plans`, `ai_rotation_decisions` (CASCADE).
9. **Stitcher:** `stitcher_config` (single row id=1).
10. **SOTG:** `sotg_shows`, `sotg_links` (CASCADE),
    `sotg_assignments` (CASCADE, UNIQUE(link_id, scheduled_date)).
11. **Settings/users/audit:** `settings` (key/value), `users`,
    `access_log`, `schema_migrations`.

### Cascade caveat (critical for deletes)

Some FKs declare `ON DELETE CASCADE`, but the LIVE dev DB was created
from an older schema where some cascades weren't present. Therefore:

- **Use the dedicated `db.delete_*()` methods**, never raw
  `DELETE FROM`, for: `campaigns`, `songs`, `jingles`, `sweepers`,
  `jingle_pads`, and `clocks`.
- `db.delete_clock` (fixed commit `d65ba98`) manually cascades
  clock_slots / auto_schedule / ai_rotation_decisions (DELETE) +
  broadcast_log / force_clocks (NULL-out to preserve history).

### Destructive operation protocol (NON-NEGOTIABLE)

Caused a real incident 2026-05-04 (deleted 15 campaigns + 791 rows
via a malformed `LIKE '__%'`). Rules:
1. Never use `LIKE` on names for cleanup. Use `WHERE id IN (…)` or
   exact `WHERE name = '…'`.
2. If `LIKE` unavoidable, escape: `LIKE 'foo\_%' ESCAPE '\'`.
3. Always `SELECT COUNT(*)` first; show count + sample; get explicit
   confirmation.
4. Wrap multi-row cleanup in `BEGIN TRANSACTION; … COMMIT;`.
5. Use `db.delete_*()` methods for the cascade-sensitive tables.

---

## PART 9 — TESTING

- **Framework:** pytest + pytest-qt. Run with `py -m pytest`.
- **Count:** ~860 tests across ~80 files.
- **Live DB:** tests run against the real dev DB (test-debt,
  documented). Fixtures use unique prefixes + try/finally cleanup so
  they don't pollute operator data. `conftest.py` provides headless
  qapp (`-platform minimal`), a session-wide bass_init/bass_free, an
  `engine` fixture (fresh AudioEngine per test), and song-path
  pickers that skip cleanly if no playable file exists.
- **Mock pattern:** `_FakeAudioEngine`, `_FakeScheduler`, `_FakeIJE`,
  `_RecordingSignal`, etc. A `_FakeScheduler` must carry ALL signals
  Studio connects to or `Studio.__init__` crashes.
- **`MainWindow(db=db)` not positional** — the ctor is
  `__init__(self, db_ok=True, song_count=0, db=None)`.

### The BASS multi-load segfault flake (KNOWN, pre-existing)

Running multiple BASS-touching test files in ONE pytest process can
segfault at teardown ("Windows fatal exception: access violation").
Each file passes IN ISOLATION.

- ✅ Safe: `py -m pytest tests/test_engine_load_play.py -q`
- ❌ May segfault: combining SOTG + Studio + Stitcher engine files
  in one run.
- **Workaround:** run per-file. This does NOT affect the shipped app.

Also: a wall-clock-boundary flake in a 1Hz-timer test (re-run) and a
modal-dialog teardown flake in `test_playlists_screen.py` (re-run).

---

## PART 10 — CONVENTIONS (follow without being told)

### Coding style
- Cache QGradient / QColor / QFont in `__init__` (perf invariant).
- Partial repaints via `self.update(QRect)`, not bare `self.update()`.
- `event.rect()` clipping in every custom `paintEvent`.
- NO DB calls in `paintEvent`; NO `self.update()` inside `paintEvent`.
- Drop shadows via `QGraphicsDropShadowEffect` (one per widget), not
  hand-painted blurs.
- Throttle engine signals (position ≤4Hz for display, levels ≤30Hz).
- `try/except` every scheduler `_on_tick` / dispatch path — broadcast
  safety; a bad row must never kill the loop.
- `dict(sqlite3.Row)` is BANNED (raises on Python 3.14). Use
  `{k: row[k] for k in row.keys()}`.
- Path resolution via `core.paths.resource_path` — no hardcoded paths.

### Commit discipline
- One focused commit per task on `native-pyqt6`.
- Explicit `git add <files>` — NEVER `git add -A`.
- Heredoc or `-F` commit message; body = problem + root cause + fix +
  test delta.
- End message with:
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`
- No `--no-verify`, no `--amend`. New commits only.
- Push to `native-pyqt6` ONLY, and only when the operator says "push".
- Commit only after operator-confirmed-working (not test-only evidence).

### Workflow
- Investigation-first: read 3-4 files, post a 4-line summary, WAIT
  for confirmation before editing.
- Hindi-English is fine; plain Hindi for verification questions.
- Senior-dev pushback ON: surface prompt-vs-code contradictions first.
- Smoke-test cycle: operator launches `py main.py`, tests visually,
  says "perfect"/"commit". Exit 0 = operator closed the window (not a
  crash); exit 127 IS a crash.

---

## PART 11 — CURRENT STATE & KNOWN ISSUES (as of HEAD `cac4adc`, 2026-05-17)

### Git state
- Branch `native-pyqt6`, HEAD `cac4adc`, 0 unpushed.
- **Substantial uncommitted work on disk** — the 2026-05-17 session
  made ~10 file edits + 4 new files but did NOT commit (operator
  deferred). See HANDOVER_2026_05_17.md for the recommended 5-commit
  batch plan. **Next session's likely first task: commit these.**

### Working features (operator-verified)
Full distribution pipeline (installer), Studio broadcast, clock-based
scheduling, AI rotation (Time-Slot Freshness), SOTG end-to-end,
FIFO pending spots/SOTG with SOTG>Spot priority, T-60s upcoming
preview, scrollable Available Clocks panel, songs import without ID3
tags, sweeper-picker broken-file filter, stable queue (no 1Hz
reshuffle).

### Known open issues / pending work
1. **BASSmix migration deferred** (Invariant #1). Retry needs
   isolation testing via `scripts/diag_mixer_stutter.py`.
2. **Audio Cue Editor** — "partially built" per CLAUDE.md. Finishing
   it would let the operator set per-song `mix_point_ms` +
   `fade_out_ms` (which the defer-fade logic already reads). HIGH
   value next task.
3. **Auto-Cue scanner** — not built. librosa + pydub background
   analysis on song import to auto-populate cue points. Industry
   standard (mAirList / Jazler).
4. **Sweepers Library data cleanup** — 3 active sweepers have empty
   file_path in the operator's DB. The picker filters them
   defensively but the data should be cleaned (attach files,
   deactivate, or delete).
5. **Some stub buttons** are intentionally silent (Instant Jingles
   AutoGain/MixFade, Spot Programming Set Mode/Mass Priorities) —
   operator's "lock unbuilt features" directive; do NOT add "coming
   soon" toasts.
6. **Code-signing cert** — installer is unsigned (SmartScreen
   "Unknown Publisher"). For commercial distribution.

---

## PART 12 — HOW TO FIX A BUG (the workflow)

1. **Reproduce / understand.** Read the operator's description. If
   it's about audio/dispatch, the flow in PART 6 is your map.
2. **Investigate first.** Grep + read the relevant files. Post a
   4-line summary: symptom, suspected root cause, proposed fix,
   test impact. WAIT for the operator's "go".
3. **Check the invariants (PART 3).** Make sure your fix doesn't
   touch `route_via_mixer`, `_has_pending_dispatch` gates, or
   `_suppress_queue_emit` unless that IS the task.
4. **Implement** minimally and in the surrounding code's style.
5. **Test.** Run the relevant test file(s) PER-FILE (segfault flake).
   Add/adjust tests. Keep the suite green.
6. **Smoke.** Launch `py main.py --debug` in the background; the
   operator tests visually and reports back. Watch the debug log.
7. **Commit only when the operator confirms** ("perfect"/"commit").
   Explicit `git add`, focused message, Co-Authored-By line. Push
   only on "push".

### Where things live (quick lookup)
- Audio playback bug → `core/audio/engine.py` + `ui/studio.py` handlers.
- "What plays next" wrong → `core/scheduler/engine.py` pickers.
- Rotation / freshness → `core/rotation_ai_engine.py`.
- Spot/SOTG dispatch/order → `ui/studio.py` (FIFO + EOS paths + PART 6.3).
- Queue panel weirdness → `ui/studio.py` `_load_upcoming_queue` /
  `_refresh_upcoming_panel` / `_check_upcoming_dispatches` +
  scheduler `queue_changed`.
- Clock/slot editing → `ui/clock_editor.py` + `ui/auto_schedule.py`.
- Any SQL / delete → `core/database.py` (use `db.delete_*`).
- A screen's layout → that screen's file (docstring has Figma node
  + ASCII layout).

---

## PART 13 — HANDOVER FILE INDEX (historical context)

Read these only when you need history on a specific feature:

| File | What it covers |
|---|---|
| HANDOVER_2026_05_17.md | **Latest.** BASSmix attempt+rollback, FIFO spots, defer-fade, sweeper filter, import relaxation, queue stability, 3 invariants, 5-commit plan. |
| HANDOVER_2026_05_16.md | Packaging: PyInstaller + Inno Setup installer, paths migration (Phase L), splash, icon, delete_clock cascade fix, dialog positioning fix. |
| HANDOVER_2026_05_15.md | Scheduling Automation submodule: RotationAIEngine, sister groups, Daily Plan Review, Time-Slot Freshness algorithm. |
| HANDOVER_2026_05_14_v2.md | Operator profile, full NIGHT_LOG #1-20, established conventions, SOTG end-to-end build. |
| HANDOVER_2026_05_13.md and earlier | Older feature history. |
| NIGHT_LOG.md | Cumulative forensic incident log (the DELETE-with-LIKE incident, BASS flake, etc.). |

---

## PART 14 — THE 60-SECOND MENTAL MODEL (if you read nothing else)

RadioAI Studio Pro plays radio. A **SchedulerEngine** walks a
**clock** (an ordered list of slots for the current hour) and picks
the next item; the **AudioEngine** (BASS) plays it; **Studio** (the
UI) shows it and handles transitions. When an **ad (spot)** or a
**voice drop (SOTG)** is due, it queues in a FIFO list and fires
after the current song ends (SOTG before Spot before Song), with NO
fade-overlap so the talk isn't buried under music. **RotationAIEngine**
keeps songs fresh (no repeat at the same hour on consecutive days).
Everything is SQLite (`core/database.py`), everything is PyQt6, audio
is BASS via pybass3. Three invariants are locked (mixer off, pending
gate, suppress-emit). Trust the code over the old docs. Investigate,
summarize, confirm, then edit — and commit only when the operator
says so.

**Jai Shree Ram. Welcome to the project.**
