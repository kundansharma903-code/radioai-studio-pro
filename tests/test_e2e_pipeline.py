"""
End-to-end pipeline smoke (Phase F P4).

Exercises the full data-layer pipeline that ships with the F1+F2+F3 work:
  Clock-with-Song-slots → auto_schedule assignment → SchedulerEngine
  pick_next_song → broadcast_log row attribution.

Does NOT cover audio playback — that's manual-test territory documented
in NIGHT_LOG_3.md and verified via main.py.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from core.database import Database
from core.scheduler.engine import SchedulerEngine


def _make_e2e_clock(db: Database) -> int:
    """Create a 4-slot clock (4 Song slots, no category constraint) and
    return its id. Used for the E2E pipeline test."""
    cid = db.create_clock("E2E Pipeline Test")
    slots = []
    for _ in range(4):
        slots.append({
            "slot_type": "Song",
            "category_id": None,
            "energy_pref": "Any",
            "vocal_pref": "Any",
            "priority_pref": "Normal",
            "is_break": 0,
            "item_id": 0,
        })
    db.save_clock_slots(cid, slots)
    return cid


def _now_at_hour(weekday: int, hour: int) -> datetime:
    base = datetime.now().replace(hour=hour, minute=0, second=0, microsecond=0)
    delta = (weekday - base.weekday()) % 7
    return base + timedelta(days=delta)


# ── Full pipeline smoke ─────────────────────────────────────────────────

def test_e2e_clock_to_broadcast_log(qtbot):
    """Walk the full data flow:
       1. Create a 4-Song-slot clock
       2. Assign to (Mon, 11) in auto_schedule
       3. SchedulerEngine.pick_next_song picks a song with attribution
       4. log_play writes a broadcast_log row with clock_id+slot_idx
       5. Read back the row — attribution intact

    Cleans up after itself."""
    db = Database()
    songs = list(db.get_songs(limit=1))
    if not songs:
        pytest.skip("no songs in DB to run the E2E pipeline")

    cid = _make_e2e_clock(db)
    db.set_auto_schedule_cell(0, 11, cid)
    sch = SchedulerEngine(db=db)

    try:
        # Step 1 — pick a song from the clock
        picked = sch.pick_next_song(_now_at_hour(0, 11))
        assert picked is not None, "scheduler returned None for live cell"
        assert picked["clock_id"] == cid
        assert picked["slot_idx"] in (0, 1, 2, 3)
        song = picked["song"]
        assert song.get("id")

        # Step 2 — log it as a scheduler-driven play
        db.log_play(
            entry_type="song",
            song_id=int(song["id"]),
            duration_ms=int(song.get("duration_ms") or 180000),
            deck="A", was_manual=0,
            clock_id=int(picked["clock_id"]),
            slot_idx=int(picked["slot_idx"]),
        )

        # Step 3 — read back the most recent log entry, verify attribution
        row = db._conn().execute(
            "SELECT song_id, clock_id, slot_idx, was_manual, entry_type "
            "FROM broadcast_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert row is not None
        assert int(row["song_id"]) == int(song["id"])
        assert int(row["clock_id"]) == cid
        assert int(row["slot_idx"]) == picked["slot_idx"]
        assert int(row["was_manual"]) == 0
        assert str(row["entry_type"]) == "song"

        # Step 4 — second pick advances cursor (rotation)
        second = sch.pick_next_song(_now_at_hour(0, 11))
        assert second is not None
        # Index advanced (or wrapped)
        assert second["slot_idx"] != picked["slot_idx"] or len(
            list(db.get_clock_slots(cid))) == 1
    finally:
        # Cleanup order: broadcast_log rows reference the clock via FK
        # with RESTRICT default — wipe them first, then the cell, then
        # the clock itself.
        db.clear_auto_schedule_cell(0, 11)
        db._conn().execute(
            "DELETE FROM broadcast_log WHERE clock_id = ?", [cid])
        db._conn().commit()
        try:
            db.delete_clock(cid)
        except ValueError:
            pass    # last-clock guard — leave it
