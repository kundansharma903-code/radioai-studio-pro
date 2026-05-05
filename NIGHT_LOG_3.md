# NIGHT_LOG_3 — overnight Phase F finish (2026-05-04 → 2026-05-05)

> Per-phase log for the overnight session that closed F2 → F1 → P2
> scheduler wiring → F3 Hub. Companion to MORNING_BRIEFING_3.md.

---

## Phase ledger

| Phase | What | Commit  | Tests   |
|-------|------|---------|---------|
| F1    | Auto Schedule UI (Figma 161:2) | `1bd832d` | 91/91 |
| P2    | Scheduler ↔ Clock wiring       | `d13679e` | 98/98 |
| F3    | Scheduling Hub (Figma 50:2)    | `94d35d7` | 103/103 |
| P4    | E2E pipeline smoke + this log  | (this commit) | 104/104 |

---

## P4 — End-to-End Smoke

### Programmatic verification (automated)

`tests/test_e2e_pipeline.py::test_e2e_clock_to_broadcast_log` walks the
full data-layer pipeline:

1. **Setup**
   - `db.create_clock("E2E Pipeline Test")` — fresh clock id
   - `db.save_clock_slots(cid, [4 × Song slot dicts])`
   - `db.set_auto_schedule_cell(0, 11, cid)` — assign Mon 11:00 to it
2. **Pick**
   - `SchedulerEngine.pick_next_song(<datetime: Mon 11:00>)`
   - asserts: `picked["clock_id"] == cid`, `slot_idx ∈ {0..3}`,
     `picked["song"]` is a real songs row
3. **Log**
   - `db.log_play(entry_type="song", song_id=…, clock_id=cid,
     slot_idx=picked["slot_idx"], was_manual=0)`
4. **Read back**
   - newest broadcast_log row has matching `song_id`, `clock_id`,
     `slot_idx`, `was_manual=0`, `entry_type="song"`
5. **Rotation**
   - second `pick_next_song` advances cursor (different `slot_idx`)
6. **Cleanup**
   - delete broadcast_log rows pinned to the test clock
   - clear the schedule cell
   - delete the clock (skips if last-clock guard fires)

Result: **PASSED** in 0.19s (run before this commit).

### Manual GUI verification plan (operator runs)

The audio playback path is not exercisable from automated tests. To
verify the full live broadcast loop, the operator should:

1. **Setup**
   - Launch `py main.py`
   - Control Panel → click **Scheduling** card → Hub opens
   - From Hub, click **Clock Editor** card. Build a clock with 4 Song
     slots in different categories. Save.
   - Header nav → click **Scheduling**. The Auto Schedule grid loads.
   - Click the cell for today's day-of-week and the *current* hour
     (e.g. Tue 09:00 if running at ~09:15). Pick the clock you just
     made. Save.
   - Open **Spots & Commercials** (Control Panel → Spots) and schedule
     a campaign break ~60–90 seconds from now.

2. **Execute**
   - F9 → Studio
   - Click **Start Scheduler**. The AUTO MODE pill should solid-fill.
   - Watch the Now Playing card pick up the first scheduler-driven
     song (the song will be from one of your 4 Song slots).
   - When the campaign break time hits, the deck stops and the spot
     plays.
   - On spot EOS, Studio resumes with the *next* clock-slot song
     (cursor advanced past the pre-spot anchor).
   - History panel shows new rows; the song rows now have
     `clock_id` + `slot_idx` populated.
   - ON AIR pill solid red while playing; AUTO MODE pill solid purple
     while scheduler is running.

3. **Inspect**
   - Quit the app cleanly (X in title bar)
   - Open the DB at `%LOCALAPPDATA%/RadioAI/radioai.db` and:
     ```sql
     SELECT id, played_at, entry_type, song_id, clock_id, slot_idx, was_manual
     FROM broadcast_log
     ORDER BY id DESC LIMIT 10;
     ```
   - Scheduler-driven songs: `clock_id` + `slot_idx` set, `was_manual=0`.
   - Manual deck plays: stay unlogged (the audition policy in Phase D5
     applies regardless of whether the scheduler is running).
   - Spot rows: `entry_type='spot'`, `campaign_id` set, `clock_id` null.

### Known limitations of P4

- The automated test does not verify *audio* playback — it only
  exercises the data layer (DB + scheduler + broadcast_log).
- Hour rollover requires waiting for the system clock to cross an
  hour boundary, or simulating it with a different `now=` arg passed
  to `pick_next_song`. The unit tests `test_hour_rollover_resets_cursor`
  cover the simulated case; the GUI path defaults to wall-clock now.
- Campaign break triggering still uses the existing Phase D4 flow —
  P2 didn't touch spot scheduling, only the song-selection layer.

---

## Phase F status as of this log

- **F1 ✓** — Auto Schedule (Figma 161:2)
- **F2 ✓** — Clock Editor (Figma 59:2)
- **P2 ✓** — Scheduler reads clocks (`pick_next_song`)
- **F3 ✓** — Scheduling Hub (Figma 50:2)
- **F4–F8** — stubs deferred (P5 if time permits, otherwise next session)
- **Phase F marker** — pending (P6, after P5 attempt)

— Claude
