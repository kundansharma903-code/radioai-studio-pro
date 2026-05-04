# Current Task State — Resume Point

> Read `PROJECT_CONTEXT.md` first for the macro view.
> This file is the **micro view** — exactly where work was paused.

---

## Active task

**Phase 5 — Audio Cue Editor dialog** (Figma node `30:2`, target 920×680, BaseDialog).

This is the **last pending dialog** in the Songs Library group.

## Phase status

| Phase | Status |
|---|---|
| 5-A — skeleton + waveform + 6 stationary markers + time ruler | ✅ **APPROVED by user** (Screenshot 1 reviewed) |
| 5-B — drag + cue cards + fade sliders + validation | 🟡 **AMBIGUOUS — see below** |
| 5-C — options bar + metadata + AI banner + DB save + integration polish | ⏳ NOT STARTED |

### Phase 5-B status: AMBIGUOUS

**What's true:**
- Code committed to disk in `ui/dialogs/audio_cue_editor_dialog.py`.
- `_CueWaveformWidget` extended with drag handlers, hit-test, clamping, hover cursor.
- New widgets: `_CueCard`, `_VerticalFadeSlider` — wired into the controls row.
- `_validate()` method, footer-message swap, Save button gating — all present.
- Screenshot 2 captured at `screenshots/audio_cue_editor_markers.png`.
- User received the screenshot.

**What's NOT true:**
- User has **NOT manually verified** interactions in the running app.
- User has **NOT explicitly said "APPROVE 5-B"**.
- Performance under drag is unverified.
- Clamping behavior unverified.
- Validation system unverified.

**Required first action in new session:**
1. Confirm the two context files have been read.
2. Wait for user "launch main.py" (or equivalent).
3. Run the app in background.
4. User runs the 12-point manual interaction checklist below.
5. **Then** either approve and proceed to 5-C, or iterate on any reported issues.

**DO NOT** assume Phase 5-B works because code is present. Manual verification is mandatory.

## Decisions already made (don't re-litigate)

| | |
|---|---|
| Q1 — Waveform | **Synthetic** (sin + noise, no real amplitude data — Phase 5+ enhancement) |
| Q2 — Markers | All 6 draggable |
| Q3 — Preview audio | **Stub** — log + 500ms green flash; real audio is its own follow-up phase |
| Q4 — Validation | **Enforce order constraint:** START ≤ INTRO ≤ HOOK IN < HOOK OUT ≤ OUTRO ≤ MIX. Hook duration must be ≥ 100ms. |
| Q5 — Trigger placement | **Option (a)** — ✎ Edit Cues button in Songs Library detail panel form-fields area. Placeholder placement done in 5-A; final placement to be revisited in 5-C. |

## Files modified during this session

### `core/database.py`
- Added `_ensure_song_cue_columns()` — idempotent migration for 6 columns: `auto_cue`, `normalize`, `bit_depth_32`, `title_field_mode`, `artist_field_mode`, `update_on_play`. **Migration has run** — songs table now has 50 columns.
- Added `_CUE_FIELDS` tuple (canonical column names list).
- Added `get_song_cue_data(song_id)` — returns flat dict of all cue-relevant fields + duration_ms + file_path + title + artist.
- Added `save_song_cue_points(song_id, data)` — writes only canonical `_ms` columns that exist.
- Added TODO comment block flagging the legacy column-duplication on songs (intro_point_ms vs intro_end_ms etc.) for future schema cleanup phase.

### `ui/dialogs/audio_cue_editor_dialog.py` (NEW)
**Phase 5-A pieces:**
- File header with PERFORMANCE NOTES block (Spot Programming lessons inherited)
- `_WaveformIcon`, `_SongInfoCard` — header chrome
- `_CueWaveformWidget` — synthetic 110-bar waveform with 5 color zones + 6 markers + time ruler. Public API: `set_duration_ms`, `set_positions`, `get_positions`, `nudge_marker`, `reset_marker`. Signal: `marker_changed(str, int)`.
- `AudioCueEditorDialog` class with `_build_header`, `_build_content`, `_build_footer`, `_populate_from_db`. Loads cue data from DB on open.

**Phase 5-B pieces (committed but unverified):**
- `_CueWaveformWidget` extended: `setMouseTracking(True)`, hit-test (`_marker_at`), clamping (`_clamp_marker` with HOOK_MIN_MS=100ms), drag handlers (`mousePressEvent`/`mouseMoveEvent`/`mouseReleaseEvent`/`leaveEvent`), cursor changes on hover, bounded `self.update(rect)` during drag.
- `_CueCard(QFrame)` — 102×110 card with header / time / `<<` `>>` nudge / PREVIEW / Reset. Hold-to-repeat enabled (`setAutoRepeat(True)`, delay=500, interval=100). Signals: `nudged`, `reset_clicked`, `preview_clicked`. `flash_preview()` for 500ms green-tint stub.
- `_VerticalFadeSlider(QFrame)` — 50×220 vertical QSlider 0-2000ms, 50ms snap, "OFF" display when value=0 in Fade Out. Signal: `value_changed(int)`.
- `_build_controls_row()` returns QHBoxLayout: Play/Stop column + Fade In + 6 _CueCards + Fade Out.
- `_make_transport_button(glyph, color, tooltip)` for Play/Stop visual stubs.
- Wiring: waveform → `_on_marker_changed` updates ALL cards (because clamping may shift neighbors); cards → `_on_card_nudge` → waveform.nudge_marker; etc.
- `_validate()` — checks 6 ordering rules, enables/disables Save, swaps footer message between tip and red error.
- Footer: `_footer_msg_lbl` exposed for the swap; Save now enabled by default (validation gates it).

### `ui/songs_library.py`
- Added "✎ Edit Cues" button in detail panel below the AI Insight box (temporary placement per Phase 5-A guardrail; final placement in Phase 5-C).
- Added `_open_cue_editor` method + `_on_cues_saved` slot.

## Phase 5-B — manual interaction checklist (run this in main.py)

When new session starts, run `py main.py` and verify each:

| # | Test | Expected |
|---|---|---|
| 1 | Hover any marker on the waveform | Cursor → open hand |
| 2 | Drag START right (within bounds) | Snaps to 0.1s, time on START card updates real-time |
| 3 | Try to drag START past INTRO | Clamps — won't ghost past |
| 4 | Drag HOOK OUT below HOOK IN+100ms | Clamps (hook duration ≥ 0.1s rule) |
| 5 | Click `<<` on INTRO card | Time decreases by 0.1s |
| 6 | Click `>>` on HOOK OUT card | Time increases (or clamps if neighbor blocks) |
| 7 | Hold `>>` for 1 second | Continues nudging at 100ms intervals |
| 8 | Click PREVIEW on any card | Button flashes green for 500ms + log line "preview <marker> at <ms>" |
| 9 | Click Reset on a card | Cue restored to default fraction of duration |
| 10 | Drag Fade In slider | Value updates "0ms" → "1500ms" |
| 11 | Drag Fade Out slider, drop at 0 | Reads "OFF" instead of "0ms" |
| 12 | Force invalid via crafty boundary | Save button disables + red error message in footer |

## Phase 5-C — what's left (after 5-B is approved)

1. **Options bar** (40px tall) — Variable Length toggle / Reset / AutoCue / Volume slider / Normalize / 32-bit toggle. Placeholder dashed box currently shown.
2. **PUBLIC ANNOUNCEMENT METADATA** section (60px) — Title Field input ("AUTO"), Artist Field input ("AUTO"), "Update on Play" dropdown. Placeholder dashed box currently.
3. **AI auto-fill banner** (40px, purple gradient) — "✦ AI will auto-detect and fill metadata from audio file tags on import" + subtitle. Placeholder dashed box currently.
4. **Real save flow** — `_on_save` currently just emits the signal + accepts. Phase 5-C wires:
   - Collect waveform marker positions (`waveform.get_positions()`)
   - Collect fade slider values
   - Collect option toggles (variable_length, auto_cue, normalize, bit_depth_32)
   - Call `db.save_song_cue_points(song_id, data)`
   - Emit `cues_saved(song_id)` for Songs Library to refresh
5. **Songs Library integration polish** — the temporary Edit Cues button currently sits below AI Insight box. Decide final placement. Possibly wire the existing "Audio Cues" tab in detail panel to switch view, but that's tab-system work and probably its own task.

## Constraints to respect

- ⚠ **No git repo locally** — `E:\RadioAI_v2\` does not have a `.git` folder. `git status` returns "fatal: not a git repository". User commits from elsewhere. Do not attempt `git init` without explicit approval — risks creating a divergent local repo from whatever the user uses.
- ⚠ **No real audio playback in Phase 5** — PREVIEW/Play/Stop are stubs by design. Do not "helpfully" wire pybass3 here; the user explicitly approved stubbing.
- ⚠ **AcmeCorp Holiday Push 02 (id=18) is real demo data** in the DB. Don't delete during cleanup. It also has 2 break_schedule rows now (per the last test session log).
- ⚠ **15 campaigns exist in DB after the recovery script ran** — IDs 1-15 (recovered) + id=18 (AcmeCorp). ID=13 ("Hello") was deleted by user via the Delete button — that's an expected user action, not a bug.
- ⚠ **Use `_ms` cue columns only** when writing — `start_point_ms`, `intro_point_ms`, `hook_in_ms`, `hook_out_ms`, `outro_point_ms`, `mix_point_ms`. Legacy text columns (`intro_time`, `mix_point`, etc.) stay untouched.

## Test artifacts

| File | Purpose |
|---|---|
| `screenshots/audio_cue_editor_skeleton.png` | Phase 5-A approved screenshot — skeleton + waveform + stationary markers |
| `screenshots/audio_cue_editor_markers.png` | Phase 5-B awaiting-approval screenshot — adds cue cards + fade sliders + Play/Stop column |
| `design_refs/audio_cue_editor_30_2.png` | Figma 30:2 reference (visual ground truth) |
| `design_refs/_screenshot_cue_editor.py` | Harness — captures audio_cue_editor_skeleton.png |
| `design_refs/_screenshot_cue_editor_5b.py` | Harness — captures audio_cue_editor_markers.png |

## Next exact action for new session

1. Read `PROJECT_CONTEXT.md` (macro)
2. Read this file (micro)
3. Run `py main.py` → Songs Library → click any song row → click **✎ Edit Cues** button
4. Walk through the 12 interaction checks in §"Phase 5-B — manual interaction checklist"
5. **If user approves visually + functionally:** proceed to Phase 5-C
6. **If issues found:** iterate, re-screenshot, re-test
7. After Phase 5-C: final commit (whatever git workflow the user has)

---

## Quick Memory Hooks for the new session

Anticipated clarifying questions and the user's decided answers — so the new session doesn't re-litigate settled calls:

**Q:** "Should I wire pybass3 for PREVIEW buttons?"
**A:** **NO.** Per Phase 5 Q3 decision, audio playback is **stubbed** throughout the cue editor (PREVIEW + Play + Stop). Real wiring is its own follow-up phase that handles all 10 audio call sites consistently with proper state management.

**Q:** "Should I extend `WaveformWidget` instead of building new?"
**A:** **NO.** Already decided to build new `_CueWaveformWidget` (private to `audio_cue_editor_dialog.py`). The existing `ui/widgets/waveform_widget.py` is decorative-only for Studio/Library compact panels — different concerns (no markers, no zones, no drag).

**Q:** "Should the 'Edit Cues' button go in the Audio Cues tab?"
**A:** **NO.** The detail-panel tab system isn't wired (clicking the tab buttons doesn't switch content — they're visual only). Use form-fields-area placement (option (a) from Q5). Tab-system fix is its own task. Phase 5-A added a temporary button; Phase 5-C will revisit final placement.

**Q:** "Should I `git init` the local project?"
**A:** **NO.** User commits from elsewhere via a separate workflow. Local `E:\RadioAI_v2\` is intentionally not git-initialized. Don't touch git here without explicit approval — risks creating a divergent local repo.

**Q:** "What if the song has no audio file or `duration_ms` is unset?"
**A:** Use `song.duration_ms` from DB if present. If `0` or missing, fall back to `180000ms` (3 min) and `log.warning` "Audio file not found — using stored duration". Markers stay placeable; PREVIEW buttons should be disabled with a tooltip when audio is missing (Phase 5-C polish).

**Q:** "What if user wants real waveform amplitude data later?"
**A:** Currently **synthetic** (sin + noise per-zone, deterministic seed=2026). Real amplitude reading via `BASS_ChannelGetData` or scipy is a future enhancement task — flagged but **not** part of Phase 5. Visual fidelity > amplitude accuracy.

**Q:** "Should I add a duplicate-name check on song / campaign edit?"
**A:** **No, unless asked.** Edit flow doesn't currently enforce uniqueness; songs and campaigns can legitimately share names (different albums, different time windows). Adding it is feature creep for Phase 5.

**Q:** "Schema has duplicate columns (`intro_point_ms` vs `intro_time` etc.) — should I clean them up?"
**A:** **NO.** Legacy columns stay for backward-compat. Phase 5+ writes only to canonical `_ms` columns. Schema cleanup is a future migration phase.

**Q:** "Should I touch the existing detail panel tab system to make 'Audio Cues' tab work?"
**A:** **No.** Tab-switching is out of scope for Phase 5. Add the Edit Cues trigger as a button only.

**Q:** "How should I save fade values?"
**A:** Sliders are 0–2000ms, snap to 50ms. Save to canonical columns: `fade_in_ms`, `fade_out_ms`. Volume goes to `volume_level` (0–100). Variable Length / AutoCue / Normalize / 32-bit are integer 0/1.
