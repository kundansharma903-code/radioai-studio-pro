# NIGHT_LOG_4 — Phase F-Final rotation engine (2026-05-04 → 2026-05-05)

> Per-subphase log for the Phase F-Final session that closed the
> Jazler-equivalent rotation backbone. Companion to MORNING_BRIEFING_4.md.

---

## Subphase ledger

| Subphase | What | Commit | Tests added | Tests total |
|----------|------|--------|-------------|-------------|
| S1 | Rotation schema + seed (voice_tracks table, clock_slots.selection_mode, sweepers + station_ids + voice_tracks seed) | `be8a362` | +4 | 113 |
| S2 | Picker functions (song with separation, jingle, sweeper, station_id, voice_track, break) + force_clocks resolution layer | `bce8693` | +11 | 124 |
| S3 | Studio item-type-aware dispatch (pick_next_item + entry_type-aware log_play + Now Playing badges) | `7e77970` | +5 | 129 |
| S4 | Force Clocks functional UI (Add / list / Delete + per-row selection) | `ba839fd` | +3 | 132 |
| S5 | Final Log generator (real impl) — 24-hour pre-compute + UI wiring + Hub badge | `0d16e52` | +4 | 136 |

Net new tests across F-Final: **+27** (S1: 4, S2: 11, S3: 5, S4: 3, S5: 4).

---

## End-of-night manual smoke plan

The data-layer pipeline is fully covered by automated tests
(`tests/test_e2e_pipeline.py` + the per-subphase tests above). For audio
playback verification, the operator should:

1. **Setup**
   - Launch `py main.py`
   - Control Panel → **Scheduling** card → Hub
   - Click **+ New Clock**. Build a clock with mixed slots:
     `Song → Jingle → Song → Break → Sweeper → Station ID`.
     For each slot, leave selection_mode at `random_from_category` (the
     default) and pick a category where appropriate. Save.
   - Header → **Scheduling** (or Hub → **Auto Schedule** card).
     Click today × current-hour cell. Pick the new clock. Save.
   - **Spots & Commercials** → schedule a campaign break for the current
     hour, ~60–90 seconds out.

2. **Optional: Force Override**
   - Hub → **Force Clocks** card → **+ Add New**
   - Use today's date with time range covering current hour
   - Save. The override should now win over the auto_schedule cell —
     visible in the resolution path.

3. **Generate the Final Log**
   - Hub → **Final Log** card → **▶ Generate Log Now**
   - Dialog reports `entry_count`, `hours_resolved`, `hours_empty`,
     `warning_count`. Center list populates with one row per pre-picked
     item, scheduled_time prefixed by hour.

4. **Live playback**
   - F9 → Studio → **Start Scheduler**
   - Watch ALL slot types play in sequence — not just songs.
     Now Playing card shows type-specific badges:
       - `[Jingle] [Auto]` for jingle slots
       - `[Sweeper] [Auto]` for sweepers
       - `[Station ID] [Auto]` for station IDs
       - `[Voice Track] [Auto]` for voice tracks
       - `[Ad Break] [Auto]` for spot/break slots that pulled a campaign
   - When the campaign break time hits, the Break slot in the clock
     pulls the campaign spot (coordinated via `_fired_breaks` so
     spot_due doesn't double-fire).

5. **Inspect**
   - Quit cleanly (X)
   - DB at `%LOCALAPPDATA%/RadioAI/radioai.db`:
     ```sql
     SELECT id, played_at, entry_type, song_id, clock_id, slot_idx
     FROM broadcast_log
     ORDER BY id DESC LIMIT 20;
     ```
     Expect rows with `entry_type` ∈ `{song, jingle, sweeper, station_id,
     voice_track, spot}`. song_id only set for `entry_type='song'`.
     clock_id + slot_idx attribute every scheduler-driven row.
     ```sql
     SELECT scheduled_time, entry_type, title_override, artist_override
     FROM final_log_entries
     WHERE log_id = (SELECT id FROM final_logs ORDER BY id DESC LIMIT 1)
     ORDER BY position LIMIT 30;
     ```
     The pre-computed plan from step 3.

### Known gaps (operator-side)

- **Audio files** for sweepers / station IDs / voice tracks aren't
  attached to the seed rows (`file_path = ''`). The picker returns
  the row; Studio's `engine.load_file('')` will fail — expect a
  warning in the log and the deck will skip that item. Wire real
  audio paths via the SongsLibrary / Pallets / a future "Add Sweeper"
  flow.
- **Separation rules** in the Final Log generator use the live
  `broadcast_log` (not a synthetic same-day set), so generated logs
  may show same-artist proximity violations. Mark for Phase F polish.

---

## Verification: programmatic E2E

`tests/test_e2e_pipeline.py::test_e2e_clock_to_broadcast_log` still
passes after every commit — that walks the data path end to end.
Picker tests (`tests/test_rotation_pickers.py`) cover each rotation
type in isolation. Final-log generator tests
(`tests/test_final_log_generator.py`) cover the 24-hour pre-compute.

All 136 tests passing as of `0d16e52`.

— Claude
