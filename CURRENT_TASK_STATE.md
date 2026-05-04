# Current Task State — Resume Point

> Read `PROJECT_CONTEXT.md` first for the macro view.
> This file is the **micro view** — exactly where work was paused.

---

## Active task

**Phase F — Scheduling UI** — kickoff. F2 Clock Editor first (decided 2026-05-04).

Eight Phase F screens planned (~7–8 days total). Build order locked:

| Order | Code | Screen | Figma |
|---|---|---|---|
| 1st | F2 | **Clock Editor** | `165:2` |
| 2nd | F1 | Main Auto Schedule | `161:2` |
| 3rd | F3 | Scheduling Hub | `50:2` |
| 4th+ | F4 | AI Magic | `170:2` |
| | F5 | Spots AI Monitor | `174:2` |
| | F6 | Add Clock dialog | TBD |
| | F7 | Force Clock dialog | TBD |
| | F8 | Settings (clocks tab) | TBD |

**F2 first because:**
- F1 needs clocks to exist before it can assign them to hours
- F2 surfaces "what is a clock?" data model questions early
- F2 has self-contained UX (one screen, one purpose) — easier to ship + iterate
- Hub-without-content (F3) = empty calories

## Phase F kickoff — decisions made

- **Order:** F2 → F1 → F3 → ...
- **Approach for each F screen:** day-by-day cadence with explicit Q&A before each day, mirroring Phase D's pattern. Small phase → screenshot → user approval → next.
- **Pre-planning report delivered (in chat) but NOT YET APPROVED.** User asked for handoff package before building. The pre-planning report is below.

## Pre-planning report — F2 Clock Editor (delivered, awaiting approval)

### 1. Figma 165:2 anatomy

Three-column 1440×900 layout:
- **Header:** brand · nav (Control Panel / Scheduling / **Clock Editor** active) · live clock · station pill · Open Studio CTA
- **LEFT 210px:** sidebar with two tab bars
  - Tab 1: Songs / Jingles / Spots / Sweepers / **Events** (filters the slot list below)
  - Tab 2: Category / Specific Song / Specific Artist (alternate ways to specify song slot content)
  - Filters: Categories list, Properties (All), Vocal Type (All)
  - Scales: Time Period, Priority, BPM, Year (decorative? sub-filters?)
  - "1,962 Songs" count card + Reset Filters / Preview Songs buttons
- **CENTER 720px:**
  - Top: CLOCK NAME field, time range "06:00 → 10:00", Comments, 5 counters (Songs / Breaks / Jingles / Sweepers / Total)
  - Action toolbar: Change · Delete · + Add · Insert · Move Up · Move Down · AI Optimise · Preview · Validate · Save Clock
  - **Slot list (12 visible rows):** `# | TYPE pill | EST. START → END | DESCRIPTION | CATEGORY pill`
  - Type pills: Song (cyan), Sweeper (orange), Jingle (purple), Spot (red)
- **RIGHT 280px:** SLOT PROPERTIES panel
  - "EDITING: Slot 1 — Song" label
  - Slot Type dropdown · Category dropdown · Energy / Vocal / Priority / Separation dropdowns
  - Apply Changes / Remove Slot buttons
  - "Morning Drive Overview" stats (Songs/Breaks/Jingles/Total)
  - Category Slots distribution bars (Hot Currents 7 slots / Classics 3 / Pop 2 / Dance 3)
- **Footer:** AUTO MODE · AI Active · 8 Clocks · Log Ready pills + center text + Open Studio button

### 2. Figma 161:2 anatomy (F1 — for context, not F2 build)

7-day × 24-hour grid. LEFT sidebar lists named clocks with color tags + time ranges + day-of-week count. CENTER grid: hour rows × 7 day columns, cells colored by assigned clock. Toggle: Weekdays / Specific Days. Top-right: Clear All. Bottom-left action: SET >> / Duplicate Clock / Auto Program Settings / Delete Clock.

**Not in F2 scope.** F2 builds the clocks; F1 wires them to hours.

### 3. Schema (already migrated — no changes needed for F2)

| Table | Key columns | Existing rows |
|---|---|---|
| `clocks` | id, name, time_start, time_end, day_mask (127=all), description, is_active | 26 |
| `clock_slots` | id, clock_id, slot_type (text), category_id, energy_pref, vocal_pref, priority_pref, separation_override, position_minutes, slot_order, is_break, sweeper_position, item_id | 291 |
| `auto_schedule` | id, clock_id, day_of_week (0=Mon), hour_start, hour_end | 88 |
| `force_clocks` | id, name, clock_id, override_date, time_start, time_end, is_recurring, recur_month, recur_day, is_active | 0 |

### 4. Existing code findings

**🚨 Module-package collision:** `core/scheduler.py` (legacy file, pre-D3) coexists with `core/scheduler/` (Phase D3 package). Python prefers the package, so the legacy `Scheduler` class wrapping `AutoScheduler` is **dead/unreachable**. Recommended cleanup: delete `core/scheduler.py` in a prep commit before F2.1 build starts.

`core/auto_scheduler.py` lingers as reference for slot-type semantics; not consumed by anything live.

No existing Clock Editor UI — fully greenfield.

### 5. Slot type semantics (from `auto_scheduler.py` + Figma)

| `slot_type` | What it does | Properties used |
|---|---|---|
| `Song` | Pick from category matching energy/vocal/priority filters with separation gap | All filters apply |
| `Jingle` | Pick from jingles by category | category_id |
| `Sweeper` | Overlay on PREVIOUS song; positioned by `sweeper_position` (START_OF_SONG / BEFORE_INTRO / BEFORE_END / BRIDGE_AT_END / CUSTOM / INDEPENDENT) | sweeper_position, item_id |
| `Spot` | Reserve for ad break — actual content from `campaign_schedule` rows hitting that hour | `is_break=1` |

`Events` (5th tab in Figma sidebar) is future — recommend skip in F2.

### 6. Architecture proposal

- **File structure:** `ui/clock_editor.py` single file (target ~700 lines).
- **State on the screen:** `_clock_id`, `_slots` (working copy list), `_selected_slot_idx`, `_is_dirty` bool.
- **DI pattern:** Same Option C as Phase B/D — accept `db` (mandatory) + optional `engine` for future preview wiring.
- **Save semantics:** Working copy → on "Save Clock" click, transactional update (UPDATE clocks WHERE id=? + DELETE FROM clock_slots WHERE clock_id=? + INSERT each slot, all wrapped). Per CLAUDE.md guardrails: OK because `WHERE id = ?` exact match.
- **SchedulerEngine integration:** **NONE in F2.** F2 is data-only. The Phase D3+ scheduler reads `campaign_schedule` for spots, not `clock_slots`. Studio's song queue is still the simple Phase D2 `LIMIT 12` from DB — clock-driven queue building is **Phase E**.

### 7. Day breakdown — F2 ~3-4 days

| Day | Scope | Est |
|---|---|---|
| **F2.1** | Skeleton: header + 3-column layout + clock-name field + counts strip + action toolbar (visual stubs) + empty slot table + empty properties panel. Hardcoded "Morning Drive Clock" as the editing target. Screenshot checkpoint. | 1 day |
| **F2.2** | Real DB integration — load any clock's slots, render in table; click a row → properties panel populates. Dropdown options come from real DB (categories, energy enums, etc.) | 1 day |
| **F2.3** | Mutations — Add/Insert/Delete/Move Up/Move Down on the slot table (in-memory working copy, dirty flag), Apply Changes / Remove Slot in properties panel, transactional Save Clock. | 1 day |
| **F2.4** | Polish + tests + Phase F2 close-out — Validate stub, AI Optimise stub, EST. START→END computed from cumulative durations, ~5 unit tests. | 0.5–1 day |

### 8. Pending decisions (Q1–Q8) — answer these before F2.1 build

These were posed at the end of the pre-planning report but not yet answered. New session should re-pose them and wait for explicit answers + GO before starting F2.1.

1. **`core/scheduler.py` legacy** — delete as prep commit (recommend) or leave as dead code?
2. **Slot types in F2.1** — all 4 (Song/Jingle/Sweeper/Spot) or song-only and add others later? Recommend all 4.
3. **Sidebar filters (Categories / Properties / Scales / Songs Found counter)** — visual-only in F2.1, wire in F2.2/F2.3 only if "Specific Song" mode is needed?
4. **Sub-tab modes (Category / Specific Song / Specific Artist)** — Category mode only for F2 ship, others deferred?
5. **Validate button** — stub-only with toast in F2; implement properly in Phase E?
6. **AI Optimise button** — stub only, Phase E AI integration?
7. **Entry point to Clock Editor** — Control Panel card / Studio status pill / new menu? Need user decision.
8. **Edit-existing or new-clock flow?** — F2 ships edit-existing only with a "Change" button opening a clock-picker; new-clock dialog deferred?

## Files modified during this session (Phase D arc)

### `core/audio/engine.py`
- Phase B4: added `probe_duration_ms(path)` and `load_file(path, loop=False)` parameter (BASS_SAMPLE_LOOP flag)
- Phase B5: `cleanup_all` per-channel error isolation; lifecycle docstrings

### `core/audio/_bass.py`
- Phase B4: added `BASS_SAMPLE_LOOP = 4` constant

### `core/instant_jingle_engine.py`
- Phase B4: rewritten as a thin adapter over `core.audio.AudioEngine` (was direct-BASS). Constructor takes `engine=`; pad_id → channel_id map; polyphony cap filtered to JINGLE channels only; `pad_ended` signal now actually wired (was declared-but-not-wired pre-rebase).

### `ui/main_window.py`
- Phase B1+: instantiates `AudioEngine` (Option C singleton)
- Phase B5: `closeEvent` + `aboutToQuit` both call `_cleanup_engine()` (idempotent)
- Phase D1: passes `engine` + `scheduler` to Studio; F9 keyboard shortcut → Studio; mounts Studio in QStackedWidget
- Phase D3+: instantiates `SchedulerEngine`; `_cleanup_engine` stops scheduler FIRST then audio cleanup

### `ui/songs_library.py`
- Phase B2: row-preview wiring (15s cap), `_on_row_play_clicked` toggle ▶↔■, waveform driven by engine.position_changed, `hideEvent` cleanup

### `ui/dialogs/audio_cue_editor_dialog.py`
- Phase 5-A/B/C: full Cue Editor build
- Phase B1: PREVIEW + Play/Stop wired; waveform playhead overlay; `done()` override cleans up the channel

### `ui/spots_commercials.py`
- Phase B3: Now Airing strip play button + state-driven progress + countdown + `_on_airing_play_clicked` toggle ▶↔■

### `ui/instant_jingles.py`
- Phase B4: passes shared engine to `InstantJingleEngine`

### `ui/widgets/waveform_widget.py`
- Phase B2: `set_animated` renamed to `set_auto_animate`; stops timer when disabled

### `core/scheduler/__init__.py`, `engine.py`, `events.py` (NEW in Phase D3)
- D3: `SchedulerEngine(QObject)` on QThread; lifecycle + tick + signal architecture
- D4: real `_dispatch_due_events` reading `campaign_schedule`, day-rollover detection, dedupe, `next_break_in` per-tick countdown signal

### `core/database.py`
- Phase D4: `get_active_breaks_for_day(day_of_week)` helper for scheduler
- Phase D6: `get_history(limit, entry_types)` extended to include both songs and spots, JOIN with campaigns table

### `ui/studio.py` (NEW — Phase D1, extended through D6)
- D1: full UI skeleton — 14 internal widgets, three-column 1440×900 layout per Figma 182:2
- D2: deck playback wired to AudioEngine; transport controls; master vol; queue double-click → load+play; idle state vs playing state
- D4: `_on_scheduler_spot_due` real spot playback + broadcast_log persistence; Now Playing card + waveform driven for spots
- D5: 4-path EOS handler (auto-advance / loop / stop-next / spot-resume); `_compute_next_song`; `_pre_spot_song_id` anchor
- D6: history list DB-driven (`_refresh_history`), status bar pills state-driven (`_update_status_pills`), AI Insights footer marker

### `tests/`
- B5: `test_engine_lifecycle.py` (5 tests)
- D3: `test_scheduler_lifecycle.py` (5 tests)
- D4: `test_scheduler_dispatch.py` (5 tests)
- D6: `test_studio_eos_paths.py` (4 tests)

### `.gitignore`
- D6: extended with `figma_*.png` + `design_refs/figma_*.png` glob patterns (replaces hand-listed entries)

## Constraints to respect

- ⚠ **Don't break Phase A + B + D tests** (74/74 must hold).
- ⚠ **Phase B audio surfaces unaffected** during Phase F builds — Songs Library / Audio Cue Editor / Spots Now Airing / Instant Jingles all use the shared `AudioEngine` and must keep working.
- ⚠ **`core/scheduler.py` legacy file** — shadowed dead code; recommend delete before F2.1 build but ASK before doing it.
- ⚠ **Performance invariants** apply to any new custom-paint widget in F2 (event.rect() clipping for the slot table, no nested QScrollArea, no DB calls in paintEvent).
- ⚠ **Database singleton** — never instantiate Database() multiple times; use `Database()` to get the same singleton.
- ⚠ **broadcast_log policy** — only scheduler-triggered spots get logged; manual deck plays from Studio do NOT log (audition only).

## Next exact action for new session

1. Read `PROJECT_CONTEXT.md` (macro)
2. Read this file (micro)
3. Pose Q1–Q8 from §"Pending decisions" above to the user
4. Wait for explicit answers + "GO F2.1"
5. Build F2.1 skeleton: `ui/clock_editor.py` with three-column layout matching Figma 165:2 + screenshot checkpoint
6. Commit + push as `feat: Phase F2.1 — Clock Editor skeleton (Figma 165:2)`
7. Propose F2.2 plan
8. Repeat per Phase D cadence

---

## Quick Memory Hooks for the new session

**Q:** "Should I auto-start the SchedulerEngine in main.py?"
**A:** **NO.** D3 explicitly chose not to auto-start. The scheduler stays manually started. Phase E will wire auto-start once production safeguards are in place.

**Q:** "Should I write to broadcast_log for manual deck plays?"
**A:** **NO.** Manual = audition. Only scheduler-triggered spots write to broadcast_log. This is the Q5/D4 contract.

**Q:** "Should I delete `core/scheduler.py` legacy file?"
**A:** **Recommend yes, but ASK first.** It's shadowed dead code since Phase D3 (the package took over). Either delete in a prep commit before F2.1, or leave it as dead code with a comment.

**Q:** "Should I touch `core/audio_engine.py` legacy?"
**A:** **NO unless explicitly asked.** Untouched throughout Phase A + B + D. Owns `bass_init` / `bass_free`. The legacy single-deck class is dead but the module is the canonical BASS lifecycle owner.

**Q:** "Should the Studio's queue be refreshed from DB on each scheduler tick?"
**A:** **NO in Phase F.** Studio's `_load_queue_from_db` runs once at construction. Dynamic refresh is Phase E (when AI rotation drives queue selection).

**Q:** "Should I add Validate / AI Optimise actually working in F2?"
**A:** **NO. Stubs only.** Validate logs + toast "checks passed" (real impl Phase E). AI Optimise is a Phase E AI hook.

**Q:** "Should I support Specific Song / Specific Artist modes in F2?"
**A:** **No, Category mode only for F2 ship.** Specific modes need song-search UX that's its own week.

**Q:** "Schema mismatch?"
**A:** **Trust schema reality over spec.** Run `PRAGMA table_info(<table>)` before coding. Past sessions caught several mismatches this way.

**Q:** "How do I know what's already wired?"
**A:** Read CLAUDE.md + this file's §"Files modified during this session." Phase B/D close-out markers in git log are also definitive.
