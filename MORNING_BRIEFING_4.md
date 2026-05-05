# MORNING BRIEFING 4 — Phase F-Final rotation engine complete (2026-05-05)

> Overnight session that closed the Jazler-equivalent rotation backbone:
> 5 subphases (S1–S5), one commit each, +27 tests, 136/136 passing.

---

## TL;DR

**Backbone live ✓.** Studio's auto-advance now plays ALL six clock-slot
types (Song / Jingle / Sweeper / Station ID / Voice Track / Break),
not just songs. Each play writes to broadcast_log with the correct
`entry_type` and clock attribution.
**Force Clocks override layer is wired** — pick_next_item resolves
through force_clocks before falling back to auto_schedule, and the
F6 UI is now functional (Add / Delete works against the live table).
**Final Log generator (F4) is real** — Hub → Final Log → Generate Log
Now pre-computes the entire day from clocks + assignments + picker
dispatch, persisted in `final_log_entries`. Hub's "Log Ready" badge
reflects today's status.
**Tests: 136/136 passing** (started F-Final at 109; +27 net new).
**Branch: `native-pyqt6`** — pushed through `0d16e52`.

## What's new

```
S1  feat: rotation schema + seed (voice_tracks table,
       clock_slots.selection_mode, 3 sweepers + 2 station IDs +
       2 voice tracks via seed_rotation_test_data())
S2  feat: picker functions for full Jazler rotation set
       (_pick_song with 60-min artist / 4-hr song separation,
        _pick_jingle / _pick_sweeper / _pick_station_id /
        _pick_voice_track with date-window filter / _pick_break
        with _fired_breaks dedupe + force_clocks resolution)
S3  feat: Studio item-type-aware dispatch
       (_compute_next_song now uses pick_next_item; entry_type
        flows through to broadcast_log; Now Playing badges
        per type: Jingle / Sweeper / Station ID / Voice Track / Ad Break)
S4  feat: Force Clocks functional UI
       (Add Override modal → db.add_force_clock; Delete confirms
        and removes; selection state drives the right-panel detail card)
S5  feat: Final Log generator (real impl)
       (db.generate_final_log walks all 24 hours, dispatches each
        clock_slot through scheduler.pick_next_item, persists to
        final_log_entries; Hub Log Ready badge reads real status)
```

## Wiring at a glance

```
┌─────────────────────── pick_next_item resolution ─────────────────────┐
│                                                                       │
│   Studio.next ─── scheduler.pick_next_item(now) ──┐                   │
│                                                   │                   │
│   ┌─ force_clock_for(now) ───── if found ─── clock_id ←┘             │
│   │       ↓ (else)                                                    │
│   └─ auto_schedule[(dow, hour)] ── clock_id                          │
│                                                                       │
│   clock_id → clock_slots[cursor++] → dispatch by slot_type:           │
│      song        → _pick_song (with separation rules)                 │
│      jingle      → _pick_jingle (jingle_pads)                         │
│      sweeper     → _pick_sweeper (sweepers table)                     │
│      station_id  → _pick_station_id (jingles WHERE category='Station ID')│
│      voice_track → _pick_voice_track (date-window filter)             │
│      break/spot  → _pick_break (campaign_schedule + _fired_breaks)    │
│                                                                       │
│   → {item_type, item_id, file_path, title, artist, duration_ms,       │
│      clock_id, slot_idx}                                              │
│                                                                       │
│   → Studio.deck.play(file_path)                                       │
│   → broadcast_log row (entry_type=item_type, clock_id, slot_idx)      │
└───────────────────────────────────────────────────────────────────────┘
```

## How to test

### Quick smoke
```
py main.py
```
Watch the log — every screen + scheduler subsystem should `ready` cleanly.

### Programmatic E2E
```
py -m pytest -m "not slow" -q
```
Should report `136 passed, 1 deselected`.

### Live audio path (NIGHT_LOG_4.md "End-of-night manual smoke plan")

The full step-by-step is in [NIGHT_LOG_4.md](NIGHT_LOG_4.md). High-level:
1. Build a clock with mixed slots (Song / Jingle / Song / Break / Sweeper / Station ID).
2. Assign to today's current hour via Auto Schedule.
3. Optionally add a Force Clock override.
4. Hub → Final Log → Generate Log Now (verify entries appear).
5. Studio → Start Scheduler → watch ALL slot types play in sequence.
6. After quitting, inspect broadcast_log + final_log_entries — all six
   `entry_type` values should appear.

## Known issues

- **Seed audio paths are empty.** The seeded sweepers / station IDs /
  voice tracks have `file_path=''` so live playback of those items will
  log an engine load failure and the deck will skip them. Wire real
  audio paths via SongsLibrary / Pallets editing or a future "Add
  Sweeper" flow. This is **expected** for the seed data — the picker
  layer still works, the audio layer just needs files attached.
- **Final Log separation** uses the live broadcast_log instead of a
  synthetic same-day set. A clock that picks the same artist twice in
  consecutive slots will produce a violating final_log_entries pair.
  Phase F polish.
- **Hour rollover during long generation** isn't a problem because the
  generator walks a fixed 24-hour grid; the live scheduler's hour
  rollover (resets cursor) is unrelated.
- **One leaked test clock** (`E2E Pipeline Test`, id ~35 from prior
  session — already documented in MORNING_BRIEFING_3.md) is still
  there. Delete via Clock Editor sidebar if you want a clean list.

## Next session recommendation

Now that the rotation backbone is solid, **Phase E (Anthropic Claude
integration)** is the right next step. The hooks are all in place:

- **Hub → Generate Today's Log** — currently stubbed to a toast. Phase E
  replaces it with Claude composing the day from clocks + auto_schedule
  + scheduling_rules + category health, calling the same picker shapes
  but with smarter filling.
- **Clock Editor → Auto-Optimise This Clock** — currently stub toast.
  Phase E sends the clock + slot list + recent broadcast_log to Claude,
  gets back rebalance suggestions.
- **Hub → AI SCHEDULING INSIGHT** card — placeholder copy. Phase E
  populates with real rotation analysis.
- **Final Log generator** — already deterministic; Phase E layer can
  rewrite the generator path to use Claude for variety + listener-flow
  optimisation, while keeping the deterministic path as a fallback.

The Phase E spec needs to land first — outline the Claude prompt schema
+ JSON response shape that the UI consumes. Once that's settled, wiring
is straightforward across these 4 hooks.

— Claude
