# MORNING BRIEFING 3 — Phase F complete (2026-05-04 → 2026-05-05)

> Overnight session that closed all of Phase F: F2 rewrite → F1 →
> scheduler-wiring → F3 Hub → P4 E2E doc → F4–F8 stubs → Phase F marker.

---

## TL;DR

**Live wired ✓** — Studio reads clocks via `pick_next_song`; scheduler
attribution lands in `broadcast_log.clock_id` + `slot_idx`.
**All Phase F screens shipped.** F2 + F1 + Hub real; F4–F8 Figma-faithful
skeletons with stubbed actions.
**Tests: 109/109 passing** (1 slow deselected). Started at 80; +29 net new.
**App smoke clean.** Every screen boots with its `ready (Figma X:Y)` line.
**Branch: `native-pyqt6`** — pushed through `2471807` (commits below).

## What's new

| Phase | Commit  | Files | Tests |
|-------|---------|-------|-------|
| F2.3 (rewrite — earlier session) | `55bd3bc` | clock_editor.py | 12 |
| F1 Auto Schedule (Figma 161:2)   | `1bd832d` | auto_schedule.py + db methods | +6 |
| P2 Scheduler-clock wiring        | `d13679e` | scheduler/engine.py + studio.py + broadcast_log migration | +7 |
| F3 Scheduling Hub (Figma 50:2)   | `94d35d7` | scheduling_hub.py + Control Panel rewire | +5 |
| P4 E2E pipeline + NIGHT_LOG_3    | `ff87ed0` | tests/test_e2e_pipeline.py + NIGHT_LOG_3.md | +1 |
| P5 F4–F8 stubs                   | `2471807` | final_log + log_viewer + force_clocks + playlists + rebroadcast | +5 |
| P6 Phase F marker (this commit)  | (this)    | — | — |

### Wiring at a glance

```
Control Panel ── Scheduling card ──► F3 Hub ─┬─► Clock Editor (F2)
                                              ├─► Auto Schedule (F1)
                                              ├─► Final Log (F4)
                                              ├─► Force Clocks (F6)
                                              ├─► Playlists (F7)
                                              ├─► Log Viewer (F5)
                                              ├─► Rebroadcast (F8)
                                              └─► RDS Settings (Phase G toast)

Studio.next_song ─┐
                  ├─ scheduler running? ──► SchedulerEngine.pick_next_song(now)
                  │                            └─► auto_schedule[(dow, hour)]
                  │                                  └─► clocks.id
                  │                                       └─► clock_slots (cursor++)
                  │                                             └─► get_songs(category, energy, vocal)
                  │                                                   └─► song dict + clock_id + slot_idx
                  │                                                         └─► broadcast_log row
                  └─ otherwise ─────► in-memory queue (Phase D5 path)
```

## How to test

### Quick smoke
```
py main.py
```
Watch the log. Should see:
- `ClockEditor ready (Figma 59:2)`
- `AutoSchedule ready (Figma 161:2)`
- `SchedulingHub ready (Figma 50:2)`
- `FinalLog / LogViewer / ForceClocks / Playlists / Rebroadcast` all `ready`

### Full live verification (NIGHT_LOG_3.md "Manual GUI verification plan")

1. Launch `py main.py`. Control Panel → **Scheduling** card → **Hub**.
2. Hub → **Clock Editor** card. Build a clock with 4 Song slots in
   different categories. Save.
3. Header → **Scheduling**. Auto Schedule grid loads. Click today × current
   hour cell. Pick the new clock. Save.
4. Open **Spots & Commercials** (Control Panel). Schedule a campaign break
   ~60 seconds out.
5. F9 → **Studio**. Click **Start Scheduler**. Watch:
   - Now Playing picks scheduler-driven song from your clock
   - At break time, deck stops, spot plays
   - Post-spot, Studio resumes from the next clock-slot song
   - History panel populates; songs show `clock_id` + `slot_idx`
6. After quitting, peek at `broadcast_log` — scheduler-driven rows have
   `clock_id` + `slot_idx` set, manual deck plays stay null.

### Programmatic verification (already automated)
```
py -m pytest -m "not slow" -q
```
should report `109 passed, 1 deselected`.

## Known issues

- **One leaked test clock** (`E2E Pipeline Test`, id ~35) from the
  initial P4 test run before I added the broadcast_log FK cleanup. Doesn't
  affect anything — just an extra "(empty)" row in MY CLOCKS. Delete it
  manually from the Clock Editor sidebar if you want a clean list.
- **F4–F8 stubs are skeletons.** Real generation / replay scheduling /
  override editing still toast-stubbed (Phase F polish or Phase E for
  AI-driven generation).
- **AI Optimiser** in the Clock Editor + Hub computes deterministic
  cards from real slot counts. Wiring to Anthropic Claude API is Phase E.
- **F1 timeline** shows `~17 slots overflow` if you stuff more than ~17
  slots into a clock — first-iter rendering quirk; the data is fine,
  the timeline just truncates the visual.
- **Hour rollover** of `pick_next_song` requires the system clock to
  cross an hour boundary OR a different `now=` arg (tests cover the
  simulated case; live runs use wall-clock).

## Next session recommendation

Pick one of three directions:

1. **Phase E AI integration** (most impact). The Anthropic Claude API
   wiring to power: Hub's `Generate Today's Log`, F4's `AI Auto-Generate`,
   Clock Editor's `Auto-Optimise This Clock`, Hub's `AI SCHEDULING
   INSIGHT`. Spec needs to land first — sketches the Claude prompt
   schema and the JSON output shape used to populate UI.

2. **Phase F polish loop** (lower risk, fills out F4–F8 stubs).
   - F4: real Generate Log path (no AI — deterministic from clocks +
     auto_schedule)
   - F6: monthly calendar grid + Add Override flow
   - F7: real Add Songs / Move / Save flow on `playlists`
   - F8: actually record audio output to WAV + schedule replay
   This is ~2–3 days of focused work each.

3. **Phase G settings + RDS** (smallest scope). The RDS card on the Hub
   today goes to a Phase G toast. Building real RDS text config + the
   broader app preferences would close the toast loop.

My suggestion: **Phase E** — the AI integration is the differentiator
that takes RadioAI from "Jazler clone" to "AI-native". The skeletons
in F4–F8 will benefit from AI-driven population once Claude is wired,
so polishing those before AI lands is partly throwaway.

— Claude
